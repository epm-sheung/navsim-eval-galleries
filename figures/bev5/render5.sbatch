#!/bin/bash
#SBATCH --job-name=bev5
#SBATCH --account=def-furukawa
#SBATCH --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=16G --time=0:45:00
#SBATCH --output=/scratch/eddie96/eddie/navsim_pages/figures/logs/bev5_%j.out
#SBATCH --error=/scratch/eddie96/eddie/navsim_pages/figures/logs/bev5_%j.err
#SBATCH --exclude=fc10917
set -eo pipefail
module --force purge
module load StdEnv/2023 python/3.11 opencv
python3 -c "import PIL,sys;print('PIL',PIL.__version__,sys.version.split()[0])"
python3 /scratch/eddie96/eddie/navsim_pages/figures/bev5/render5.py
