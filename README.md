# TSD `conda` Channel Creator

**Disclaimer**: This is not an official TSD repository, and only something I have created to simplify my own workflow with TSD and conda environments.


This repository provides tools for maintaining an offline `conda` channel for
use on TSD. It relies on lock-files created by `pixi` package manager, to
download desired `conda`-packages into a `conda`-channel structure, which may be
synced to TSD.

## Dependencies

On you personal laptop, connected to the internet.

- pixi:

  ```bash
  curl -fsSL https://pixi.sh/install.sh | bash
  ```

- TSD api-client:

  ```bash
  https://github.com/unioslo/tsd-api-client.git
  ```

On TSD:

- conda:

## Usage guide

`pixi` can be installed by

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

Check the web-page [https://pixi.sh] for further details on how to use pixi to
manage python-environments.

I recommend to set the option:

```bash
pixi config set pinning-strategy no-pin --global
```

such that packages by default are added without version constraints. While
strict version constraints may help in creating reproducible environments, it
might be complicated when trying to install a minimally working setup on TSD.

Typical workflow is to:

1. Add all desired `conda`-packages using `pixi`
2. Ensure that the `pixi.lock` file is updated.
3. Download packages and upload to TSD as described below.
4. Re-index channel on TSD.
5. Attempt to install packages into your environment. If there are any issues
   (typically with missing or conflicting C-library versions), add the packages
   to the pixi environment with the necessary constraints. Repeat procedure for
   downloading packages, uploading to TSD, indexing the channel, and install the
   package with the classic solver.

After a few iterations with this, you might be able to install necessary
packages.

## Setup `conda` on TSD

The `conda` channel needs to be indexed on TSD for the channel cache to be
correct. Therefore, we need to install `conda-index` (previously given as the
command `conda index`) from the package `conda-build`. Recommended way is to
create a new environment on your local laptop

```bash
conda create -n conda-build conda-build
```

upload and unpack it into the correct directory on TSD. For more details about
this, see [https://conda.github.io/conda-pack/].

## Create `conda`-environment

We want to create a `conda`-channel containing packages we want, with
dependencies on TSD. Since the specific packages needed depends on the software
environment, we create these packages within a docker-container running the same
OS as the linux VM (redhat-linux 8.10 at the time of writing). Therefore, do the
following

```bash
docker run -it -v $PWD:/conda-channel --rm redhat/ubi8 bash
cd /conda-channel
bash update-channel.sh ## Performs below steps
# curl -fsSL https://pixi.sh/install.sh | bash
# source /root/.bashrc
# rm -rf pixi.lock .pixi
# pixi install
# pixi run python download_pixi_packages.py pixi.lock local_conda_repo
```

After the script exits, you may quit the docker container. To ensure that you
have all rights,

```bash
sudo chown -R $(id -u):$(id -g) * .pixi
```

followed by

```bash
tacl p2386 --upload-sync local_conda_repo --keep-missing
```

to upload the contents to the remote location. (If the repo does not already
exist, you should use --upload instead of --upload-sync)

NB: Do not have a trailing slash, i.e. `local_conda_repo/` as there is a bug in
`tacl` preventing it from finding already existing contents, and it will
reupload everything, rather than just new files.

On TSD: Set the following contents in your `.condarc`-file(typically in your
home directory).

```bash
offline: true
```

Then every time new content have been uploaded to the `local_conda_repo`, rerun
`conda-index` by activating the `conda-build` environment, and then running

```bash
python -m conda_index [path to local repo, can be .] --channeldata
```

Then `conda` should hopefully be able to install packages contained in the
`local_conda_repo`.

**NB**:

- If you get error messages telling you that the sqlite database is locked, you
  can try to limit the number of threads by using the "--threads"-argument.
  Locked-database issues seem to come from multiple threads trying to write to
  the database simultaneously, combined with slow IO on TSD.
- If you get an error `sqlite3.OperationalError: disk I/O error`, I have not
  managed to find any workaround. However, I have gotten the channel to work
  with index run from local laptop, so I recommend moving the
  "`conda_index`"-command to the step before uploading the directory. It seems
  the original issues I experienced was due to the solver, not the caching etc.

Then you should be able to install packages into your environment by:

```bash
conda install [packages] --solver=classic --offline --override-channels -c [path to channel]
```

**PS**: `--solver=classic` is needed as the `libmamba`-solver does not work
initially. However, once run with the classic solver, it seems that it is able
to find it after all. This is useful if there are version conflicts, as the
libmamba output is a lot more user friendly.

**PS:** --`override-channels` is needed due to some issues with the
`miniforge3`-conda trying to use `conda-forge` packages although it is in
`offline`-mode. There is probably some option to disable this behaviour, such
that it would suffice to specify channels within `.condarc`. Please let me know
if you find out how.
