from setuptools import setup, find_packages

setup(
    name="focus",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["click>=8.0"],
    entry_points={
        "console_scripts": [
            "focus=focus.cli:main",
        ],
    },
    python_requires=">=3.8",
)
