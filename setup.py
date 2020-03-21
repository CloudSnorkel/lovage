import os

import setuptools

# TODO lovage[runtime], lovage[aws], lovage[django]

version = os.getenv("GITHUB_REF")
if version and version.startswith("refs/tags/"):
    version = version.replace("refs/tags/", "")
else:
    version = "0.0.0"

setuptools.setup(
    name="lovage",
    version=version,
    description="Kind of like Celery, but simpler and with more Lambda",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    keywords="celery queue task lambda serverless",
    author="CloudSnorkel",
    author_email="amir@cloudsnorkel.com",
    url="https://github.com/CloudSnorkel/lovage",
    license="MIT",
    packages=["lovage"],
    package_data={"lovage": ["backends/awslambda/helpers/*.py"]},
    include_package_data=True,
    zip_safe=True,
    python_requires=">=3.6",
    setup_requires=["wheel"],
    install_requires=[
        # TODO auto sync with pipenv?
        "boto3",
        "troposphere",
        "globster==0.1.0",
    ],
)
