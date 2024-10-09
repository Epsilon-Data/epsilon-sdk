from setuptools import setup, find_packages

setup(
    name="epsilon-sdk",
    version="0.1.0",
    description="SDK for accessing remote datasets",
    packages=find_packages(),
    install_requires=[
        'pandas',  
        'requests'
    ],
)
