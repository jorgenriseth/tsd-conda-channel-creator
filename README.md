# TSD Conda Channel Creator

## Dependencies

On you personal laptop, connected to the internet. pixi:

```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

TSD api-client:

```bash
https://github.com/unioslo/tsd-api-client.git
```

## Setup conda on TSD

The conda channel needs to be indexed on TSD for the channel cache to be
correct. Therefore, we need to install conda-index (previously given as the
command `conda index`) from the package conda-build. Recommended way is to
create a new environment on your local laptop

```bash
conda create -n conda-build conda-build
```

upload and unpack it into the correct directory on TSD. For more details about
this, see [https://conda.github.io/conda-pack/].

## Create conda-environment

We want to create a conda-channel containing packages we want, with dependencies
on TSD. Since the specific pacakges needed depends on the software environment,
we create these packages within a docker-container running the same OS as the
linux VM (redhat-linux 8.10 at the time of writing). Therefore, do the following

```bash
docker run -it -v $PWD:/conda-channel bash
cd /conda-channel
curl -fsSL https://pixi.sh/install.sh | bash
source /root/.bashrc
rm pixi.lock
pixi install
pixi run python download_pixi_packages.py pixi.lock local_conda_repo
```

After the script exits, you may quit the docker container, then run

```bash
tacl p2386 --upload-sync local_conda_repo --keep-missing
```

to upload the contents to the remote location.

NB: Do not have a trailing slash, i.e. `local_conda_repo/` as there is a bug in
`tacl` preventing it from finding already existing contents, and it will
reupload everything, rather than just new files.

On TSD: Set the following contents in your `.condarc`-file(typically in your
home directory).

```bash
offline: true
channels:
  - /ess/p2386/data/durable/file-import/p2386-member-group/local_conda_repo`
```

Then every time new content have been uploaded to the `local_conda_repo`, rerun
`conda-index` by activating the `conda-build` environment, and then running

```bash
python -m conda_index /ess/p2386/data/durable/file-import/p2386-member-group/local_conda_repo --channeldata
```

Then `conda` should hopefully be able to install packages contained in the
`local_conda_repo`.
