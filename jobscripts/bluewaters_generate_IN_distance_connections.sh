#!/bin/bash
#PBS -l nodes=64:ppn=16:xe
#PBS -q high
#PBS -l walltime=5:00:00
#PBS -e ./results/generate_IN_distance_connections.$PBS_JOBID.err
#PBS -o ./results/generate_IN_distance_connections.$PBS_JOBID.out
#PBS -N generate_IN_distance_connections
### Set umask so users in my group can read job stdout and stderr files
#PBS -W umask=0027


module swap PrgEnv-cray PrgEnv-gnu
module load cray-hdf5-parallel
module load bwpy 
module load bwpy-mpi
module load atp

export ATP_ENABLED=1 
export LD_LIBRARY_PATH=/sw/bw/bwpy/0.3.0/python-mpi/usr/lib:/sw/bw/bwpy/0.3.0/python-single/usr/lib:$LD_LIBRARY_PATH
export PYTHONPATH=$HOME/model/dentate:$HOME/bin/nrn/lib/python:/projects/sciteam/baef/site-packages:$PYTHONPATH
export PATH=$HOME/bin/nrn/x86_64/bin:$PATH
export SCRATCH=$HOME/scratch

ulimit -c unlimited



set -x
cd $PBS_O_WORKDIR


aprun -n 1024 python ./scripts/generate_distance_connections.py \
       --config=./config/Full_Scale_Control.yaml \
       --forest-path=$SCRATCH/dentate/MC_forest_syns_20171013.h5 \
       --connectivity-path=$SCRATCH/dentate/MC_connections_20171026.h5 \
       --connectivity-namespace=Connections \
       --coords-path=$SCRATCH/dentate/dentate_Full_Scale_Control_coords_20171005.h5 \
       --coords-namespace=Coordinates \
       --io-size=128 --cache-size=1 --quick
