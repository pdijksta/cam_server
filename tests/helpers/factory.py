from cam_server.camera.configuration import CameraConfigManager
from cam_server.camera.management import CameraInstanceManager
from cam_server.pipeline.configuration import PipelineConfigManager
from cam_server.pipeline.management import PipelineInstanceManager


def get_test_instance_manager():
        config_manager = CameraConfigManager(config_provider=MockConfigStorage())
        camera_instance_manager = CameraInstanceManager(config_manager)

        return camera_instance_manager


def get_test_pipeline_manager():
    config_manager = PipelineConfigManager(config_provider=MockConfigStorage())
    pipeline_instance_manager = PipelineInstanceManager(config_manager, MockCamServerClient())

    return pipeline_instance_manager


class MockConfigStorage:
    def __init__(self):
        self.configs = {}

    def get_available_configs(self):
        return list(self.configs.keys())

    def get_config(self, config_name):
        if config_name not in self.configs:
            # Replicate the error in the real config provider.
            raise ValueError("Config '%s' does not exist." % config_name)

        return self.configs[config_name]

    def save_config(self, config_name, configuration):
        self.configs[config_name] = configuration

    def delete_config(self, config_name):
        del self.configs[config_name]


class MockCamServerClient:

    def get_camera_geometry(self, camera_name):
        return 100, 101

    def get_camera_stream(self, camera_name):
        return "tcp://127.0.0.1:10000"
