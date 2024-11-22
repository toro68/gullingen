from setuptools import setup

setup(
    name="gullingen",
    version="0.1",
    packages=["utils.core", "utils.db", "utils.services", "components.ui"],
    package_dir={"": "."},
    install_requires=[
        "streamlit",
        "pandas",
        "plotly",
        "numpy",
        "requests",
        "sqlite3",
        "pathlib",
        "python-dotenv",
    ],
)
