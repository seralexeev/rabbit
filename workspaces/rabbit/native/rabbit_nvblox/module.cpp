#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <cmath>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#include "nvblox/nvblox.h"

namespace nb = nanobind;

void sanitizeDepth(float* depth, int rows, int cols, float min_depth, float max_depth, const float* intrinsics,
                   const float* world_from_camera, float floor_y, float floor_snap, float max_snap_shift,
                   float far_range, float far_band_slope,
                   cudaStream_t stream);

namespace {

using DepthArray = nb::ndarray<const float, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using PoseArray = nb::ndarray<const float, nb::shape<4, 4>, nb::c_contig, nb::device::cpu>;
using Vertices = nb::ndarray<nb::numpy, float, nb::shape<-1, 3>>;
using Triangles = nb::ndarray<nb::numpy, int32_t, nb::shape<-1, 3>>;
using MeshBlock = std::tuple<int, int, int, Vertices, Triangles>;
using Clearance = nb::ndarray<nb::numpy, int16_t, nb::shape<-1, -1>>;
using ClearanceGrid = std::tuple<float, float, float, Clearance>;

const Eigen::Matrix4f kYUpToZUp = (Eigen::Matrix4f() << 1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1).finished();
constexpr float kMaxSnapShift = 0.15f;
constexpr float kFarFloorRange = 2.0f;
constexpr float kFarFloorBandSlope = 0.02f;
constexpr float kObstacleMinHeight = 0.04f;
constexpr float kObstacleMaxHeight = 0.45f;
constexpr float kMaxClearance = 2.0f;
constexpr float kUnobserved = -1000.0f;
const Eigen::Matrix4f kOpenGlToOpenCv = Eigen::Vector4f(1, -1, -1, 1).asDiagonal();

template <typename T, typename Array>
Array ownedArray(std::vector<T>&& data, size_t rows) {
  auto* owned = new std::vector<T>(std::move(data));
  nb::capsule owner(owned, [](void* p) noexcept { delete static_cast<std::vector<T>*>(p); });
  return Array(owned->data(), {rows, 3}, owner);
}

class Mapper {
 public:
  Mapper(float voxel_size, float max_integration_distance, float min_depth, float max_depth, float mesh_min_weight,
         int depth_dilations, float floor_snap)
      : voxel_size_(voxel_size),
        max_integration_distance_(max_integration_distance),
        min_depth_(min_depth),
        max_depth_(max_depth),
        mesh_min_weight_(mesh_min_weight),
        depth_dilations_(depth_dilations),
        floor_snap_(floor_snap) {
    reset();
  }

  void reset() {
    stream_ = std::make_shared<nvblox::CudaStreamOwning>();
    mapper_ = std::make_unique<nvblox::Mapper>(voxel_size_, nvblox::BlockMemoryPoolParams(),
                                               nvblox::ProjectiveLayerType::kTsdf, stream_);
    configure();
    esdf_full_ = true;
  }

  void integrate(DepthArray depth, float fx, float fy, float cx, float cy, PoseArray world_from_camera, float floor_y) {
    const int rows = static_cast<int>(depth.shape(0));
    const int cols = static_cast<int>(depth.shape(1));
    const Eigen::Map<const Eigen::Matrix<float, 4, 4, Eigen::RowMajor>> pose(world_from_camera.data());
    nvblox::Transform T_L_C;
    T_L_C.matrix() = kYUpToZUp * Eigen::Matrix4f(pose) * kOpenGlToOpenCv;
    const nvblox::Camera camera(fx, fy, cx, cy, cols, rows);
    const float intrinsics[4] = {fx, fy, cx, cy};
    nb::gil_scoped_release release;
    depth_.copyFromAsync(rows, cols, depth.data(), *stream_);
    sanitizeDepth(depth_.dataPtr(), rows, cols, min_depth_, max_depth_, intrinsics, world_from_camera.data(), floor_y,
                  floor_snap_, kMaxSnapShift, kFarFloorRange, kFarFloorBandSlope, *stream_);
    mapper_->integrateDepth(depth_, T_L_C, camera);
  }

  std::vector<MeshBlock> takeMeshUpdates(bool everything) {
    std::vector<nvblox::Index3D> blocks;
    {
      nb::gil_scoped_release release;
      mapper_->updateColorMesh(everything ? nvblox::UpdateFullLayer::kYes : nvblox::UpdateFullLayer::kNo);
      std::optional<std::vector<nvblox::Index3D>> requested;
      if (everything) {
        requested = mapper_->color_mesh_layer().getAllBlockIndices();
      }
      mapper_->serializeSelectedLayers(nvblox::LayerTypeBitMask(nvblox::LayerType::kColorMesh), -1.0f,
                                       nvblox::BlockExclusionParams(), requested);
    }
    const auto serialized = mapper_->serializedColorMeshLayer();
    std::vector<MeshBlock> result;
    result.reserve(serialized->block_indices.size());
    for (size_t block = 0; block < serialized->block_indices.size(); ++block) {
      const size_t first_vertex = serialized->vertex_block_offsets[block];
      const size_t vertex_count = serialized->vertex_block_offsets[block + 1] - first_vertex;
      const size_t first_index = serialized->triangle_index_block_offsets[block];
      const size_t index_count = serialized->triangle_index_block_offsets[block + 1] - first_index;
      std::vector<float> vertices(vertex_count * 3);
      for (size_t i = 0; i < vertex_count; ++i) {
        const auto& v = serialized->vertices[first_vertex + i];
        vertices[3 * i] = v.x();
        vertices[3 * i + 1] = v.z();
        vertices[3 * i + 2] = -v.y();
      }
      std::vector<int32_t> triangles(serialized->triangle_indices.begin() + first_index,
                                     serialized->triangle_indices.begin() + first_index + index_count);
      const auto& index = serialized->block_indices[block];
      result.emplace_back(index.x(), index.y(), index.z(), ownedArray<float, Vertices>(std::move(vertices), vertex_count),
                          ownedArray<int32_t, Triangles>(std::move(triangles), index_count / 3));
    }
    return result;
  }

  bool save(const std::string& path) {
    nb::gil_scoped_release release;
    return mapper_->saveLayerCake(path);
  }

  bool load(const std::string& path) {
    nb::gil_scoped_release release;
    const bool loaded = mapper_->loadMap(path);
    configure();
    esdf_full_ = true;
    return loaded;
  }

  bool saveMesh(const std::string& path) {
    nb::gil_scoped_release release;
    mapper_->updateColorMesh(nvblox::UpdateFullLayer::kYes);
    return mapper_->saveColorMeshAsPly(path);
  }

  ClearanceGrid clearanceGrid(float floor_y, float center_x, float center_z, float half_extent) {
    std::vector<int16_t> cells;
    float origin_x = 0.0f;
    float origin_z = 0.0f;
    size_t rows = 0;
    size_t cols = 0;
    {
      nb::gil_scoped_release release;
      if (floor_y != floor_y_) {
        floor_y_ = floor_y;
        configure();
        esdf_full_ = true;
      }
      mapper_->updateEsdfSlice(esdf_full_ ? nvblox::UpdateFullLayer::kYes : nvblox::UpdateFullLayer::kNo);
      esdf_full_ = false;
      const float slice_height = floor_y_ + (kObstacleMinHeight + kObstacleMaxHeight) / 2.0f;
      const nvblox::AxisAlignedBoundingBox window(Eigen::Vector3f(center_x - half_extent, -center_z - half_extent, -1e4f),
                                                  Eigen::Vector3f(center_x + half_extent, -center_z + half_extent, 1e4f));
      const auto aabb = slicer_.getAabbOfLayerAtHeight(mapper_->esdf_layer(), slice_height).intersection(window);
      if (!aabb.isEmpty()) {
        slicer_.sliceLayerToDistanceImage(mapper_->esdf_layer(), slice_height, kUnobserved, aabb, &slice_);
        host_slice_.copyFrom(slice_);
        rows = host_slice_.rows();
        cols = host_slice_.cols();
        origin_x = aabb.min().x();
        origin_z = -(aabb.min().y() + rows * voxel_size_);
        cells.resize(rows * cols);
        for (size_t row = 0; row < rows; ++row) {
          for (size_t col = 0; col < cols; ++col) {
            const float distance = host_slice_(static_cast<int>(row), static_cast<int>(col));
            int16_t value = -1;
            if (distance > kUnobserved / 2.0f) {
              value = static_cast<int16_t>(std::clamp(std::lround(distance * 1000.0f), 0L, 32767L));
            }
            cells[(rows - 1 - row) * cols + col] = value;
          }
        }
      }
    }
    auto* owned = new std::vector<int16_t>(std::move(cells));
    nb::capsule owner(owned, [](void* p) noexcept { delete static_cast<std::vector<int16_t>*>(p); });
    return {origin_x, origin_z, voxel_size_, Clearance(owned->data(), {rows, cols}, owner)};
  }

  void clearOutside(float x, float z, float radius) {
    nb::gil_scoped_release release;
    mapper_->clearOutsideRadius(Eigen::Vector3f(x, -z, floor_y_), radius);
  }

  void clearBelow(float y) {
    nb::gil_scoped_release release;
    const nvblox::AxisAlignedBoundingBox below(Eigen::Vector3f(-1e4f, -1e4f, -1e4f), Eigen::Vector3f(1e4f, 1e4f, y));
    mapper_->clearTsdfInsideShapes({nvblox::BoundingShape(below)});
  }

  int blocks() { return mapper_->tsdf_layer().numBlocks(); }

 private:
  void configure() {
    nvblox::MapperParams params;
    params.projective_integrator_params.projective_integrator_max_integration_distance_m = max_integration_distance_;
    params.projective_integrator_params.projective_integrator_weighting_mode =
        nvblox::WeightingFunctionType::kInverseSquareDropoffWeight;
    params.mesh_integrator_params.mesh_integrator_min_weight = mesh_min_weight_;
    params.do_depth_preprocessing = depth_dilations_ > 0;
    params.esdf_integrator_params.esdf_integrator_max_distance_m = kMaxClearance;
    params.esdf_integrator_params.esdf_slice_min_height = floor_y_ + kObstacleMinHeight;
    params.esdf_integrator_params.esdf_slice_max_height = floor_y_ + kObstacleMaxHeight;
    params.esdf_integrator_params.esdf_slice_height = floor_y_ + (kObstacleMinHeight + kObstacleMaxHeight) / 2.0f;
    params.depth_preprocessing_num_dilations = depth_dilations_;
    mapper_->setMapperParams(params);
  }

  float voxel_size_;
  float max_integration_distance_;
  float min_depth_;
  float max_depth_;
  float mesh_min_weight_;
  int depth_dilations_;
  float floor_snap_;
  float floor_y_ = 0.0f;
  bool esdf_full_ = true;
  nvblox::EsdfSlicer slicer_;
  nvblox::Image<float> slice_{nvblox::MemoryType::kDevice};
  nvblox::Image<float> host_slice_{nvblox::MemoryType::kHost};
  std::shared_ptr<nvblox::CudaStreamOwning> stream_;
  std::unique_ptr<nvblox::Mapper> mapper_;
  nvblox::DepthImage depth_{nvblox::MemoryType::kDevice};
};

}  // namespace

NB_MODULE(rabbit_nvblox, m) {
  nb::class_<Mapper>(m, "Mapper")
      .def(nb::init<float, float, float, float, float, int, float>(), nb::arg("voxel_size"),
           nb::arg("max_integration_distance"), nb::arg("min_depth"), nb::arg("max_depth"),
           nb::arg("mesh_min_weight") = 1e-4f, nb::arg("depth_dilations") = 0, nb::arg("floor_snap") = 0.0f)
      .def("reset", &Mapper::reset)
      .def("integrate", &Mapper::integrate, nb::arg("depth"), nb::arg("fx"), nb::arg("fy"), nb::arg("cx"),
           nb::arg("cy"), nb::arg("world_from_camera"), nb::arg("floor_y"))
      .def("take_mesh_updates", &Mapper::takeMeshUpdates, nb::arg("everything") = false)
      .def("save", &Mapper::save)
      .def("load", &Mapper::load)
      .def("save_mesh", &Mapper::saveMesh)
      .def("clear_below", &Mapper::clearBelow, nb::arg("y"))
      .def("clearance_grid", &Mapper::clearanceGrid, nb::arg("floor_y"), nb::arg("center_x") = 0.0f,
           nb::arg("center_z") = 0.0f, nb::arg("half_extent") = 1e4f)
      .def("clear_outside", &Mapper::clearOutside, nb::arg("x"), nb::arg("z"), nb::arg("radius"))
      .def("blocks", &Mapper::blocks);
}
