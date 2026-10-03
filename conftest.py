"""Register the optional scorecard argument before test collection."""


def pytest_addoption(parser):
    parser.addoption("--goal-scorecard", help="Write the measured goal Markdown scorecard to this path")
