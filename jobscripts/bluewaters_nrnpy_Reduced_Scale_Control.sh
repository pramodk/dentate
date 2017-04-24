#!/bin/bash

### set the number of nodes and the number of PEs per node
#PBS -l nodes=1:ppn=16:xe
### which queue to use
#PBS -q debug
### set the wallclock time
#PBS -l walltime=0:30:00
### set the job name
#PBS -N dentate_Reduced_Scale_Control
### set the job stdout and stderr
#PBS -e ./results/$PBS_JOBID.err
#PBS -o ./results/$PBS_JOBID.out
### set email notification
##PBS -m bea
### Set umask so users in my group can read job stdout and stderr files
#PBS -W umask=0027
### Get darsan profile data
#PBS -lgres=darshan

module swap PrgEnv-cray PrgEnv-gnu
module load cray-hdf5-parallel/1.8.16
module load bwpy 
module load bwpy-mpi

set -x

export LD_LIBRARY_PATH=/sw/bw/bwpy/0.3.0/python-mpi/usr/lib:/sw/bw/bwpy/0.3.0/python-single/usr/lib:$LD_LIBRARY_PATH
#export PYTHONPATH=$HOME/bin/nrn/lib/python:/projects/sciteam/baef/site-packages:$PYTHONPATH
#export PATH=$HOME/bin/nrn/x86_64/bin:$PATH
export PYTHONPATH=/projects/sciteam/baef/nrn/lib/python:/projects/sciteam/baef/site-packages:$PYTHONPATH
export PATH=/projects/sciteam/baef/nrn/x86_64/bin:$PATH
export DARSHAN_LOGPATH=$PBS_O_WORKDIR/darshan-logs

echo python is `which python`
results_path=./results/Full_Scale_Control_$PBS_JOBID
export results_path

cd $PBS_O_WORKDIR

mkdir -p $results_path

git ls-files | tar -zcf ${results_path}/dentate.tgz --files-from=/dev/stdin
git --git-dir=../dgc/.git ls-files | grep Mateos-Aparicio2014 | tar -C ../dgc -zcf ${results_path}/dgc.tgz --files-from=/dev/stdin

## Necessary for correct loading of Darshan with LD_PRELOAD mechanism
#export PMI_NO_FORK=1
#export PMI_NO_PREINITIALIZE=1
#export LD_PRELOAD=/sw/xe/darshan/2.3.0/darshan-2.3.0_cle52/lib/libdarshan.so:/opt/cray/hdf5-parallel/1.8.16/GNU/4.9/lib/libhdf5_parallel_gnu_49.so.10

aprun -n 16 \
    python main.py  \
    --config-file=config/Reduced_Scale_Control.yaml  \
    --template-paths=$HOME/model/dgc/Mateos-Aparicio2014 \
    --dataset-prefix="./datasets" \
    --results-path=$results_path \
    --io-size=1 \
    --tstop=5 \
    --v-init=-75 \
    --max-walltime-hours=0.5 \
    --ldbal \
    --lptbal \
    --verbose
