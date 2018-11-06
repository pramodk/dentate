#!/bin/bash
#
#SBATCH -J generate_DG_GC_log_normal_weights
#SBATCH -o ./results/generate_DG_GC_log_normal_weights.%j.o
#SBATCH --nodes=32
#SBATCH --ntasks-per-node=24
#SBATCH -t 3:00:00
#SBATCH --mail-user=ivan.g.raikov@gmail.com
#SBATCH --mail-type=END
#SBATCH --mail-type=BEGIN
#


module load python
module load hdf5
module load scipy
module load mpi4py

export PYTHONPATH=/share/apps/compute/mpi4py/mvapich2_ib/lib/python2.7/site-packages:/opt/python/lib/python2.7/site-packages:$PYTHONPATH
export PYTHONPATH=$HOME/bin/nrnpython/lib/python:$PYTHONPATH
export PYTHONPATH=$HOME/model:$HOME/model/dentate/btmorph:$PYTHONPATH
export SCRATCH=/oasis/scratch/comet/iraikov/temp_project
export LD_PRELOAD=$MPIHOME/lib/libmpi.so
ulimit -c unlimited

set -x

nodefile=`generate_pbs_nodefile`

mpirun_rsh -export-all -hostfile $nodefile -np 768  \
 python $HOME/model/dentate/scripts/generate_log_normal_weights_as_cell_attr.py \
 -d GC -s MPP -s LPP -s MC \
 --config=./config/Full_Scale_Control.yaml \
 --weights-path=$SCRATCH/dentate/Full_Scale_Control/DG_GC_forest_syns_log_normal_weights_20181013.h5 \
 --connections-path=$SCRATCH/dentate/Full_Scale_Control/DG_GC_connections_20180813_compressed.h5 \
 --io-size=160  --value-chunk-size=100000 --chunk-size=20000 --write-size=25 -v 


