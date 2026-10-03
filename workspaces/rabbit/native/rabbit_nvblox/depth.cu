#include <cuda_runtime.h>

struct FloorClip {
  float fx, fy, cx, cy;
  float r10, r11, r12, ty;
  float floor_y;
  float floor_snap;
  float max_snap_shift;
  float far_range;
  float far_band_slope;
};

__global__ void sanitizeDepthKernel(float* depth, int cols, int count, float min_depth, float max_depth, FloorClip clip) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count) {
    return;
  }
  float value = depth[i];
  if (!isfinite(value) || value < min_depth || value > max_depth) {
    depth[i] = 0.0f;
    return;
  }
  const float xn = (i % cols - clip.cx) / clip.fx;
  const float yn = (i / cols - clip.cy) / clip.fy;
  const float rise = clip.r10 * xn - clip.r11 * yn - clip.r12;
  if (rise < 0.0f) {
    const float height = clip.ty + value * rise;
    const float on_floor = (clip.floor_y - clip.ty) / rise;
    if (height < clip.floor_y || (height < clip.floor_y + clip.floor_snap && on_floor - value < clip.max_snap_shift)) {
      value = on_floor;
    } else if (value > clip.far_range &&
               height < clip.floor_y + clip.floor_snap + clip.far_band_slope * value) {
      value = 0.0f;
    }
  }
  depth[i] = value;
}

void sanitizeDepth(float* depth, int rows, int cols, float min_depth, float max_depth, const float* intrinsics,
                   const float* world_from_camera, float floor_y, float floor_snap, float max_snap_shift,
                   float far_range, float far_band_slope, cudaStream_t stream) {
  const FloorClip clip{intrinsics[0], intrinsics[1], intrinsics[2], intrinsics[3],
                       world_from_camera[4], world_from_camera[5], world_from_camera[6], world_from_camera[7], floor_y,
                       floor_snap, max_snap_shift, far_range, far_band_slope};
  constexpr int kThreads = 256;
  const int count = rows * cols;
  sanitizeDepthKernel<<<(count + kThreads - 1) / kThreads, kThreads, 0, stream>>>(depth, cols, count, min_depth, max_depth, clip);
}
