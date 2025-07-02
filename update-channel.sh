#!/bin/bash
set -eo pipefail
curl -fsSL https://pixi.sh/install.sh | bash
source /root/.bashrc
rm -rf pixi.lock .pixi
pixi install
pixi run python download_pixi_packages.py pixi.lock local_conda_repo
