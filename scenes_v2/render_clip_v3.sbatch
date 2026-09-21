#!/bin/bash
#SBATCH --account=def-furukawa
#SBATCH --job-name=scenes_v3_render
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/eddie96/eddie/navsim_pages/scenes_v2/logs/render_%j.out
#SBATCH --error=/scratch/eddie96/eddie/navsim_pages/scenes_v2/logs/render_%j.err
#SBATCH --exclude=fc10917,fc30532

set -e
set -x

echo "=== job $SLURM_JOB_ID on $(hostname) starting $(date) ==="

module --force purge
module load StdEnv/2023 python/3.11 opencv
echo "--- after opencv module load ---"
which python3
python3 -c "import cv2, numpy, PIL; print('cv2', cv2.__version__, 'numpy', numpy.__version__, 'PIL', PIL.__version__)" \
  || { echo "opencv module combo failed, trying scipy-stack + ffmpeg"; MOD_FAILED=1; }

if [ -n "$MOD_FAILED" ]; then
  module --force purge
  module load StdEnv/2023 python/3.11 scipy-stack ffmpeg
  echo "--- after scipy-stack+ffmpeg module load ---"
  which python3
  python3 -c "import numpy, PIL; print('numpy', numpy.__version__, 'PIL', PIL.__version__)"
  python3 -c "import cv2" 2>&1 || echo "cv2 NOT available in this combo -- script will need imageio-ffmpeg fallback"
fi

echo "=== running render_clip_v3.py ==="
python3 /scratch/eddie96/eddie/navsim_pages/scenes_v2/render_clip_v3.py

echo "=== job finished $(date) ==="
