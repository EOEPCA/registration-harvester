# EOEPCA+ Registration Harvester

<!-- PROJECT SHIELDS -->
<!--
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->

[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<!-- PROJECT LOGO -->
<br />
<p align="center">
  <a href="https://github.com/EOEPCA/registration-harvester">
    <img src="images/logo.png" alt="Logo" width="80" height="80">
  </a>

  <h3 align="center">EOEPCA+ Registration Harvester</h3>

  <p align="center">
    This repository includes the Harvester component of the EOEPCA+ Resource Registration building block
    <br />
    <a href="https://eoepca.readthedocs.io/projects/resource-registration/en/latest/"><strong>Explore the docs »</strong></a>
    <br />
  </p>
</p>

<!-- TABLE OF CONTENTS -->

## Description

The EOEPCA+ Registration Harvester is a component of the [Resource Registration](https://eoepca.readthedocs.io/projects/resource-registration/en/latest/) building block.

The functionality of the harvester is expressed through workflows which are defined as [BPMN](https://www.bpmn.org/) processes in the `workflows` directory. 

The runtime orchestration of the workflows is done by the open-source [Flowable](https://www.flowable.com/open-source) process automation platform.

The implementation of the individual workflow tasks is provided by the `worker` package, utilizing the [EOEPCA+ Registration Library](https://eoepca.readthedocs.io/projects/resource-registration/en/latest/design/common-library/design/).


### Built With

- [Python](https://www.python.org/)
- [Flowable](https://www.flowable.com/open-source)
- [FastAPI](https://fastapi.tiangolo.com/)
- [EOEPCA+ Registration Library](https://github.com/EOEPCA/resource-registration/tree/main/lib)
- [Flowable External Client Python](https://github.com/EOEPCA/eoepca-flowable-external-client-python)


## Getting Started

### Deployment

Registration Harvester deployment is described in the [EOEPCA Deployment Guide](https://eoepca.readthedocs.io/projects/deploy/en/latest/).

## Documentation

The component documentation can be found [here](https://eoepca.readthedocs.io/projects/resource-registration/en/latest/design/harvester/design/).

<!-- LICENSE -->

## License

The EOEPCA components are distributed under the Apache-2.0 License. See `LICENSE` for more information.

<!-- CONTACT -->

## Contact

Project Link: [https://github.com/EOEPCA/registration-harvester](https://github.com/EOEPCA/registration-harvester)

<!-- ACKNOWLEDGEMENTS -->

## Acknowledgements

- README.md is based on [this template](https://github.com/othneildrew/Best-README-Template) by [Othneil Drew](https://github.com/othneildrew).

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->

[contributors-shield]: https://img.shields.io/github/contributors/EOEPCA/registration-harvester.svg?style=flat-square
[contributors-url]: https://github.com/EOEPCA/registration-harvester/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/EOEPCA/registration-harvester.svg?style=flat-square
[forks-url]: https://github.com/EOEPCA/registration-harvester/network/members
[stars-shield]: https://img.shields.io/github/stars/EOEPCA/registration-harvester.svg?style=flat-square
[stars-url]: https://github.com/EOEPCA/registration-harvester/stargazers
[issues-shield]: https://img.shields.io/github/issues/EOEPCA/registration-harvester.svg?style=flat-square
[issues-url]: https://github.com/EOEPCA/registration-harvester/issues
[license-shield]: https://img.shields.io/github/license/EOEPCA/registration-harvester.svg?style=flat-square
[license-url]: https://github.com/EOEPCA/registration-harvester/blob/master/LICENSE