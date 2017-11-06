#!/bin/bash
#
#SBATCH -J dentate_Full_Scale_Control
#SBATCH -o ./results/dentate_Full_Scale_Control.%j.o
#SBATCH --nodes=70
#SBATCH --ntasks-per-node=24
#SBATCH -p compute
#SBATCH -t 4:00:00
#SBATCH --mail-user=ivan.g.raikov@gmail.com
#SBATCH --mail-type=END
#

module load python
module load hdf5
module load scipy
module load mpi4py

set -x

results_path=./results/Full_Scale_Control_$SLURM_JOB_ID
export results_path

mkdir -p $results_path

git ls-files | tar -zcf ${results_path}/dentate.tgz --files-from=/dev/stdin
git --git-dir=../dgc/.git ls-files | grep Mateos-Aparicio2014 | tar -C ../dgc -zcf ${results_path}/dgc.tgz --files-from=/dev/stdin

export PYTHONPATH=$HOME/bin/nrnpython/lib/python:$PYTHONPATH
export PYTHONPATH=$HOME/model/dentate:$PYTHONPATH
export SCRATCH=/oasis/scratch/comet/iraikov/temp_project
export LD_PRELOAD=$MPIHOME/lib/libmpi.so
ulimit -c unlimited


ibrun -np 1680 python main.py \
 --config-file=config/Full_Scale_Control.yaml  \
 --template-paths=../dgc/Mateos-Aparicio2014 \
 --dataset-prefix="/oasis/scratch/comet/iraikov/temp_project/dentate" \
 --results-path=$results_path \
 --io-size=256 \
 --tstop=500 \
 --v-init=-75 \
 --max-walltime-hours=3.5 \
 --verbose
