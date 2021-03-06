#!/bin/bash
#
#SBATCH -J generate_distance_structured_weights_DG_MC
#SBATCH -o ./results/generate_structured_weights_DG_MC.%j.o
#SBATCH -N 40
#SBATCH --ntasks-per-node=56            # # of mpi tasks per node
#SBATCH -p development      # Queue (partition) name
#SBATCH -t 2:00:00
#SBATCH --mail-user=ivan.g.raikov@gmail.com
#SBATCH --mail-type=END
#SBATCH --mail-type=BEGIN
#

module load python3
module load phdf5

export NEURONROOT=$HOME/bin/nrnpython3
export PYTHONPATH=$HOME/model:$NEURONROOT/lib/python:$SCRATCH/site-packages:$PYTHONPATH
export PATH=$NEURONROOT/x86_64/bin:$PATH

set -x


export I_MPI_EXTRA_FILESYSTEM=enable
export I_MPI_EXTRA_FILESYSTEM_LIST=lustre
#export I_MPI_ADJUST_ALLGATHER=4
#export I_MPI_ADJUST_ALLGATHERV=4
#export I_MPI_ADJUST_ALLTOALL=4

cd $SLURM_SUBMIT_DIR

ibrun python3 ./scripts/generate_structured_weights_as_cell_attr.py \
    -d MC -s CA3c \
    --config=./config/Full_Scale_GC_Exc_Sat_DD_SLN.yaml \
    --initial-weights-namespace='Log-Normal Weights' \
    --structured-weights-namespace='Structured Weights' \
    --output-weights-path=$SCRATCH/striped/dentate/Full_Scale_Control/DG_IN_syn_weights_SLN_20200112.h5 \
    --weights-path=$SCRATCH/striped/dentate/Full_Scale_Control/DG_IN_syn_weights_LN_20200112_compressed.h5 \
    --connections-path=$SCRATCH/striped/dentate/Full_Scale_Control/DG_IN_connections_20200112_compressed.h5 \
    --input-features-path="$SCRATCH/striped/dentate/Full_Scale_Control/DG_input_features_20191119_compressed.h5" \
    --arena-id=A  --field-width-scale=1.33 \
    --io-size=256 --cache-size=10  --value-chunk-size=100000 --chunk-size=20000 --write-size=4 -v

