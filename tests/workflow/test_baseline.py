def test_runtime_modules_exist():
    from image_to_3d_print.api.app import create_app
    from image_to_3d_print.jobs.worker import Worker
    from image_to_3d_print.workflow.graph import build_graph
    assert create_app and Worker and build_graph
