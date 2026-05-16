from setuptools import setup, find_packages

setup(
    name="hermes-probe",
    version="0.1.0",
    description="Hermes Protocol CLI — AI-to-AI communication protocol tools",
    packages=find_packages(),
    py_modules=["cli"],
    entry_points={
        "console_scripts": [
            "hermes-probe=cli:main",
        ]
    },
    python_requires=">=3.8",
)
