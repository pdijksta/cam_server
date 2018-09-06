import tempfile
from logging import getLogger

import numpy
import scipy
import scipy.misc
import scipy.optimize

from matplotlib import cm

from cam_server import config

_logging = getLogger(__name__)


def subtract_background(image, background_image):
    # We do not want negative numbers int the image.
    if image.shape != background_image.shape:
        raise RuntimeError("Invalid background_image size %s compared to image %s" % (background_image.shape,
                                                                                      image.shape))

    mask_for_zeros = (background_image > image)
    numpy.subtract(image, background_image.astype("uint16"), image)
    image[mask_for_zeros] = 0

    return image


def get_region_of_interest(image, offset_x, size_x, offset_y, size_y):
    return image[offset_y:offset_y + size_y, offset_x:offset_x + size_x]


def apply_threshold(image, threshold=1):
    image[image < int(threshold)] = 0


def get_min_max(image):
    return numpy.nanmin(image), numpy.nanmax(image)


def get_x_y_profile(image):
    x_profile = image.sum(0)
    y_profile = image.sum(1)
    return x_profile, y_profile


def get_intensity(profile):
    return profile.sum()


def find_index(axis, item):
    """ Find the index of the axis value that corresponds to the passed value/item"""

    left_bigger_right = axis[0] > axis[1]  # if true axis looks like this [5, 4, 3, 2, 1, 0]

    # Descending order -> [9, 8, 7, 6]
    if left_bigger_right:
        # Item value 10 -> go to first section.
        if item > axis[0]:
            return 0

        # Item value 5 -> go to last section.
        if item < axis[-1]:
            return len(axis) - 1

        # Negate the array and number to search from the right.
        return numpy.searchsorted(-axis, -item)

    # Ascending order -> [6, 7, 8, 9]
    else:
        # Item value 5 -> go to first section.
        if item < axis[0]:
            return 0

        # Item value 10 -> go to last section.
        if item > axis[-1]:
            return len(axis) - 1

        insert_index = numpy.searchsorted(axis, item)

        # If the value is the same as the array value at the given index, use this index directly.
        if insert_index < len(axis) and axis[insert_index] == item:
            return insert_index

        # Otherwise return the previous section index.
        return insert_index - 1


def get_good_region_profile(profile, threshold=0.3, gfscale=1.8):
    profile_min = profile.min()
    threshold_value = (profile.max() - profile_min) * threshold + profile_min

    # The center of the good region is defined by the index of the max value of the profile
    index_maximum = profile.argmax()

    index_start = index_maximum
    index_end = index_maximum

    for i in range(index_maximum, 0, -1):
        if profile[i] < threshold_value:
            index_start = i
            break

    for i in range(index_maximum, profile.shape[0]):
        if profile[i] < threshold_value:
            index_end = i
            break

    # Extend the good region based on gfscale
    gf_extend = (index_end - index_start) * gfscale - (index_end - index_start)

    index_start -= gf_extend / 2
    index_end += gf_extend / 2

    index_start = index_start if index_start > 0 else 0
    index_end = index_end if index_end < profile.size - 1 else profile.size - 1

    return int(index_start), int(index_end)  # Start and end index of the good region


def gauss_fit(profile, axis):
    if axis.shape[0] != profile.shape[0]:
        raise RuntimeError("Invalid axis passed %d %d" % (axis.shape[0], profile.shape[0]))

    center_of_mass = (axis * profile).sum() / profile.sum()
    center_of_mass_2 = (axis * axis * profile).sum() / profile.sum()
    rms = numpy.sqrt(numpy.abs(center_of_mass_2 - center_of_mass * center_of_mass))

    offset, amplitude, center, standard_deviation = _gauss_fit(axis, profile)
    gauss_function = _gauss_function(axis, offset, amplitude, center, standard_deviation)

    return gauss_function, offset, amplitude, center, abs(standard_deviation), center_of_mass, rms


def _gauss_function(x, offset, amplitude, center, standard_deviation):
    # return offset + amplitude * numpy.exp(-(numpy.power((x - center), 2) / (2 * numpy.power(standard_deviation, 2))))
    return offset + amplitude * numpy.exp(-(x - center) ** 2 / (2 * standard_deviation ** 2))


def _gauss_fit(axis, profile, center_of_mass=None):

    offset = profile.min()  # Minimum is good estimation of offset
    amplitude = profile.max() - offset  # Max value is a good estimation of amplitude

    if center_of_mass:
        center = center_of_mass  # Center of mass is a good estimation of center (mu)
    else:
        center = axis[profile.argmax()]

    surface = numpy.trapz((profile - offset), x=axis)
    # standard_deviation = surface / ((amplitude - offset) * numpy.sqrt(2 * numpy.pi))
    standard_deviation = surface / (amplitude * numpy.sqrt(2 * numpy.pi))

    try:
        # It shows up that fastest fitting is when sampling period is around sigma value
        optimal_parameter, _ = scipy.optimize.curve_fit(_gauss_function, axis, profile.astype("float32"),
                                                        p0=[offset, amplitude, center, standard_deviation])
    except BaseException as e:
        # print(e)
        # logging.info("COULD NOT CONVERGE!")
        optimal_parameter = [offset, amplitude, center, standard_deviation]

    return optimal_parameter


def slice_image(image, number_of_slices=1, vertical=False):
    """
    :param image:
    :param number_of_slices:
    :param vertical:            if vertical the axis to use is y, if not vertical the axis to use is x
    :return:
    """

    if vertical:
        image = image.T  # transpose

    slice_size = image.shape[0] / number_of_slices
    slices = numpy.empty((number_of_slices, image.shape[1]))

    for i in range(number_of_slices):
        slices[i] = image[i * slice_size:(i + 1) * slice_size, :].sum(0)

    return slices


def calculate_slices(axis, center, standard_deviation, scaling=2, number_of_slices=9):
    """ Calculate index list for slices based on the given axis """

    if number_of_slices % 2 == 0:
        raise ValueError("Number of slices must be odd.")

    size_slice = scaling * standard_deviation / number_of_slices

    index_center = find_index(axis, center)
    index_half_slice = find_index(axis, center + size_slice / 2)
    n_pixel_half_slice = abs(index_half_slice - index_center)

    if n_pixel_half_slice < 1:
        _logging.info('Calculated number of pixel of a slice size [%d] is less than 1 - default to 1',
                      n_pixel_half_slice)
        n_pixel_half_slice = 1

    n_pixel_slice = 2 * n_pixel_half_slice

    # Add middle slice - located half/half on center
    start_index = index_center - n_pixel_half_slice
    end_index = index_center + n_pixel_half_slice

    list_slices_indexes = []
    slice_length = None

    number_of_elements_axis = len(axis)

    if start_index >= 0 and end_index < number_of_elements_axis:

        list_slices_indexes.append(start_index)
        list_slices_indexes.append(end_index)

        # The slice length is the difference in axis value from the start to the end of the axis.
        slice_length = abs(axis[start_index] - axis[end_index])

        # We subtract 1 because we already added the middle slice.
        counter_slices = number_of_slices - 1

        # Calculate outer slices
        while counter_slices > 0:
            start_index -= n_pixel_slice
            end_index += n_pixel_slice
            if start_index < 0 or end_index >= number_of_elements_axis:
                _logging.info('Stopping slice calculation as they are out of range ...')
                # Start index cannot be smaller than 0 and end index cannot e larger than len(axis)
                break
            list_slices_indexes.insert(0, start_index)
            list_slices_indexes.append(end_index)

            counter_slices -= 2

    return list_slices_indexes, n_pixel_half_slice, slice_length


def get_x_slices_data(image, x_axis, y_axis, x_center, x_standard_deviation, scaling=2, number_of_slices=11):
    """
    Calculate slices and their statistics
    :return: <center [x,y]>, <standard deviation>, <intensity>
    """

    list_slices, n_pixel_half_slice, slice_length = calculate_slices(x_axis, x_center, x_standard_deviation, scaling,
                                                                     number_of_slices)

    slice_data = []

    for i in range(len(list_slices) - 1):
        if list_slices[i] < image.shape[-1] and list_slices[i + 1] < image.shape[-1]:
            # slices are within good region
            slice_n = image[:, list_slices[i]:list_slices[i + 1]]

            slice_y_profile = slice_n.sum(1)
            pixel_intensity = slice_n.sum()

            # Does x need to be the middle of slice? - currently it is
            center_x = x_axis[list_slices[i] + n_pixel_half_slice]

            gauss_function, offset, amplitude, center_y, standard_deviation, _, _ = gauss_fit(slice_y_profile, y_axis)
            slice_data.append(([center_x, center_y], standard_deviation, pixel_intensity))
        else:
            _logging.info('Drop slice')

    return slice_data, slice_length


def get_y_slices_data(image, x_axis, y_axis, y_center, y_standard_deviation, scaling=2, number_of_slices=11):
    """
    Calculate slices and their statistics
    :return: <center [x,y]>, <standard deviation>, <intensity>
    """

    list_slices, n_pixel_half_slice, slice_length = calculate_slices(y_axis, y_center, y_standard_deviation, scaling,
                                                                     number_of_slices)

    slice_data = []

    for i in range(len(list_slices) - 1):
        if list_slices[i] < image.shape[0] and list_slices[i + 1] < image.shape[0]:
            # slices are within good region
            slice_n = image[list_slices[i]:list_slices[i + 1], :]

            slice_x_profile = slice_n.sum(0)
            pixel_intensity = slice_n.sum()

            gauss_function, offset, amplitude, center_x, standard_deviation, _, _ = gauss_fit(slice_x_profile, x_axis)

            # Does x need to be the middle of slice? - currently it is
            slice_data.append(([center_x, y_axis[list_slices[i] + n_pixel_half_slice]], standard_deviation,
                               pixel_intensity))
        else:
            _logging.info('Drop slice')

    return slice_data, slice_length


def _linear_function(x, slope, offset):
    return slope * x + offset


def linear_fit(x, y):  # x/y arrays
    # offset = 0.0
    # slope = 0.1
    # optimal_parameter, covariance = scipy.optimize.curve_fit(_linear_function, x, y, p0=[slope, offset])
    optimal_parameter, covariance = scipy.optimize.curve_fit(_linear_function, x, y)  # No initial guesses

    return optimal_parameter  # returns [slope, offset]


def _quadratic_function(x, a, b, c):
    return a * x ** 2 + b * x + c


def quadratic_fit(x, y):
    optimal_parameter, covariance = scipy.optimize.curve_fit(_quadratic_function, x, y)

    return optimal_parameter


def get_png_from_image(image_raw_bytes, scale=None, min_value=None, max_value=None, colormap_name=None):
    """
    Generate an image from the provided camera.
    :param image_raw_bytes: Image bytes to turn into PNG
    :param scale: Scale the image.
    :param min_value: Min cutoff value.
    :param max_value: Max cutoff value.
    :param colormap_name: Colormap to use. See http://matplotlib.org/examples/color/colormaps_reference.html
    :return: PNG image.
    """

    image_raw_bytes = image_raw_bytes.astype("float64")

    if scale:
        shape_0 = int(image_raw_bytes.shape[0] * scale)
        shape_1 = int(image_raw_bytes.shape[1] * scale)
        sh = shape_0, image_raw_bytes.shape[0] // shape_0, shape_1, image_raw_bytes.shape[1] // shape_1
        image_raw_bytes = image_raw_bytes.reshape(sh).mean(-1).mean(1)

    if min_value:
        image_raw_bytes -= min_value
        image_raw_bytes[image_raw_bytes < 0] = 0

    if max_value:
        image_raw_bytes[image_raw_bytes > max_value] = max_value

    try:
        colormap_name = colormap_name or config.DEFAULT_CAMERA_IMAGE_COLORMAP
        # Available colormaps http://matplotlib.org/examples/color/colormaps_reference.html
        colormap = getattr(cm, colormap_name)

        # http://stackoverflow.com/questions/10965417/how-to-convert-numpy-array-to-pil-image-applying-matplotlib-colormap
        # normalize image to range 0.0-1.0
        image_raw_bytes *= 1.0 / image_raw_bytes.max()

        image = numpy.uint8(colormap(image_raw_bytes) * 255)
    except:
        raise ValueError("Unable to apply colormap '%s'. "
                         "See http://matplotlib.org/examples/color/colormaps_reference.html for available colormaps." %
                         colormap_name)

    n_image = scipy.misc.toimage(image)

    tmp_file = tempfile.TemporaryFile()

    # https://github.com/python-pillow/Pillow/issues/1211
    # We do not use any compression for speed reasons
    # n_image.save('your_file.png', compress_level=0)
    n_image.save(tmp_file, 'png', compress_level=0)
    # n_image.save(tmp_file, 'jpeg', compress_level=0)  # jpeg seems to be faster

    tmp_file.seek(0)
    content = tmp_file.read()
    tmp_file.close()

    return content

def get_tilt(image, x_axis, y_axis, w_order=1, order=1):
    """
    order is the is the order of the fit.
    w_order is the order of the weights in terms of the projected intensity.
    A higher w_order will put more emphasis on parts of the beam with high projected intensity.
    The output is relative to the mean image. This parameter should probably be added to the main output.
    """
    np = numpy
    max_ = np.argmax(image, axis=0)
    mean_list = y_axis[max_]
    not_nan = ~np.isnan(mean_list)

    projX = np.sum(image, axis=0)
    projX_corrected = projX - projX.min()

    mean_image = np.sum(projX_corrected*x_axis)/np.sum(projX_corrected)

    xx = x_axis[not_nan]
    yy = mean_list[not_nan]

    w = (projX_corrected[not_nan] - projX_corrected.min())**w_order
    fit = np.polyfit(xx-mean_image, yy, order, w=w)
    p = np.poly1d(fit)
    return p, mean_image

