# How to run github action with ACT locally

## Setup GITHUB_TOKEN

Write a .secrets file with GITHUB_TOKEN=...
token get from https://github.com/settings/personal-access-tokens

## Run linting

`act -j lint -P ubuntu-latest=node:16-buster-slim`

NOTE: need -P ubuntu-latest=node:16-buster-slim because need a distribution with node installed

## Run test-extract-between-commit tests

`act -j test-extract-between-commit`

or

`act -j test-extract-between-commit -P ubuntu-latest=catthehacker/ubuntu:act-latest`

note: list all jobs available with `act --list`

# run generic tests

`act -j test -P ubuntu-latest=catthehacker/ubuntu:act-latest`


## Notes about Image used by ACT

ACT try to use the image as that used in the yaml, the -P option create a mapping between the imagename in the github action yaml and a real image.
Real image will be pulled or get from local registry.
Real image is forced to be get from local registry if --pull=false option is used. This avoid to contact sur of the image and get from the local pulled one. This otpion speed-up a lot local testing and net traffic.



