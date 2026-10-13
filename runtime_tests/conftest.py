"""Register shared Runtime fixtures before test module collection."""

pytest_plugins = (
    "runtime_tests.test_delivery",
    "runtime_tests.test_project_service",
    "runtime_tests.test_project_source",
)
