#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/map.h>
#include <nanobind/stl/string.h>

#include <rtabmap/core/CameraModel.h>
#include <rtabmap/core/Link.h>
#include <rtabmap/core/Memory.h>
#include <rtabmap/core/Parameters.h>
#include <rtabmap/core/Rtabmap.h>
#include <rtabmap/core/SensorData.h>
#include <rtabmap/core/Signature.h>
#include <rtabmap/core/Statistics.h>
#include <rtabmap/utilite/ULogger.h>

#include <opencv2/imgcodecs.hpp>

#include <chrono>
#include <map>
#include <memory>
#include <string>

namespace nb = nanobind;
using rtabmap::Transform;

using Matrix4 = nb::ndarray<const double, nb::shape<4, 4>, nb::c_contig, nb::device::cpu>;
using Matrix4Out = nb::ndarray<nb::numpy, double, nb::shape<4, 4>>;

static Transform to_transform(const Matrix4& m) {
    auto v = m.view();
    return Transform(v(0, 0), v(0, 1), v(0, 2), v(0, 3), v(1, 0), v(1, 1), v(1, 2), v(1, 3), v(2, 0), v(2, 1), v(2, 2),
                     v(2, 3));
}

static Matrix4Out to_array(const Transform& t) {
    auto* data = new double[16]{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1};
    if (!t.isNull()) {
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 4; ++c) data[r * 4 + c] = t.data()[r * 4 + c];
    } else {
        data[0] = data[5] = data[10] = 1;
    }
    nb::capsule owner(data, [](void* p) noexcept { delete[] static_cast<double*>(p); });
    return Matrix4Out(data, {4, 4}, owner);
}

static cv::Mat decode(const nb::bytes& bytes, int flags) {
    cv::Mat buffer(1, static_cast<int>(bytes.size()), CV_8UC1, const_cast<char*>(bytes.c_str()));
    return cv::imdecode(buffer, flags);
}

class Localizer {
public:
    Localizer(const std::string& database, const std::map<std::string, std::string>& parameters, bool incremental) {
        ULogger::setType(ULogger::kTypeConsole);
        ULogger::setLevel(ULogger::kWarning);
        params_ = rtabmap::ParametersMap(parameters.begin(), parameters.end());
        params_[rtabmap::Parameters::kMemIncrementalMemory()] = incremental ? "true" : "false";
        rtabmap_.init(params_, database);
        last_old_id_ = rtabmap_.getLastLocationId();
    }

    ~Localizer() { close(incremental()); }

    nb::dict process(const nb::bytes& rgb, const nb::bytes& depth, const Matrix4& odom, double stamp, double fx,
                     double fy, double cx, double cy) {
        if (closed_) throw std::runtime_error("localizer is closed");
        cv::Mat image = decode(rgb, cv::IMREAD_COLOR);
        cv::Mat range = decode(depth, cv::IMREAD_ANYDEPTH);
        if (image.empty() || range.empty() || range.type() != CV_16UC1)
            throw std::invalid_argument("expected an encoded colour image and a 16-bit depth image");
        Transform odom_pose = to_transform(odom);
        rtabmap::CameraModel model(fx, fy, cx, cy, rtabmap::CameraModel::opticalRotation(), 0, image.size());
        double ms;
        bool added;
        {
            nb::gil_scoped_release release;
            rtabmap::SensorData data(image, range, model, ++frame_id_, stamp);
            auto started = std::chrono::steady_clock::now();
            added = rtabmap_.process(data, odom_pose, linear_variance_, angular_variance_);
            ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        }
        const rtabmap::Statistics& stats = rtabmap_.getStatistics();
        const auto& values = stats.data();
        auto stat = [&](const std::string& key) {
            auto it = values.find(key);
            return it == values.end() ? 0.f : it->second;
        };
        int loop = stats.loopClosureId(), proximity = stats.proximityDetectionId();
        int matched = loop ? loop : proximity;
        nb::dict out;
        out["added"] = added;
        out["id"] = rtabmap_.getLastLocationId();
        out["loop_id"] = loop;
        out["proximity_id"] = proximity;
        out["matched_id"] = matched;
        const rtabmap::Memory* memory = rtabmap_.getMemory();
        out["matched_previous_session"] =
            matched > 0 && memory->getMapId(matched, true) != memory->getMapId(rtabmap_.getLastLocationId(), true);
        out["inliers"] = static_cast<int>(stat(rtabmap::Statistics::kLoopVisual_inliers()));
        out["hypothesis"] = stat(rtabmap::Statistics::kLoopHighest_hypothesis_value());
        out["rejected"] = static_cast<int>(stat(rtabmap::Statistics::kLoopRejectedHypothesis()));
        out["process_ms"] = ms;
        out["wm_size"] = rtabmap_.getWMSize();
        out["map_correction"] = to_array(rtabmap_.getMapCorrection());
        return out;
    }

    void set_mode(bool incremental, const std::map<std::string, std::string>& parameters) {
        for (const auto& [key, value] : parameters) params_[key] = value;
        params_[rtabmap::Parameters::kMemIncrementalMemory()] = incremental ? "true" : "false";
        rtabmap_.parseParameters(params_);
    }

    bool incremental() const { return rtabmap_.getMemory() && rtabmap_.getMemory()->isIncremental(); }

    int trigger_new_map() { return rtabmap_.triggerNewMap(); }

    nb::object node_pose(int id) const {
        const auto& poses = rtabmap_.getLocalOptimizedPoses();
        auto it = poses.find(id);
        if (it == poses.end()) return nb::none();
        return nb::cast(to_array(it->second));
    }

    bool add_link(int from, int to, const Matrix4& transform, double variance) {
        cv::Mat information = cv::Mat::eye(6, 6, CV_64FC1) / variance;
        return rtabmap_.addLink(rtabmap::Link(from, to, rtabmap::Link::kUserClosure, to_transform(transform), information));
    }

    int nodes() const {
        const rtabmap::Memory* memory = rtabmap_.getMemory();
        return memory ? static_cast<int>(memory->getAllSignatureIds().size()) : 0;
    }

    void set_odometry_variance(double linear, double angular) {
        linear_variance_ = linear;
        angular_variance_ = angular;
    }

    void close(bool save) {
        if (closed_) return;
        closed_ = true;
        rtabmap_.close(save);
    }

    int last_old_id() const { return last_old_id_; }

private:
    rtabmap::Rtabmap rtabmap_;
    rtabmap::ParametersMap params_;
    int last_old_id_ = 0;
    int frame_id_ = 0;
    double linear_variance_ = 1e-4;
    double angular_variance_ = 1e-4;
    bool closed_ = false;
};

NB_MODULE(rabbit_rtabmap, m) {
    nb::class_<Localizer>(m, "Localizer")
        .def(nb::init<const std::string&, const std::map<std::string, std::string>&, bool>(), nb::arg("database"),
             nb::arg("parameters"), nb::arg("incremental"))
        .def("process", &Localizer::process, nb::arg("rgb"), nb::arg("depth"), nb::arg("odom"), nb::arg("stamp"),
             nb::arg("fx"), nb::arg("fy"), nb::arg("cx"), nb::arg("cy"))
        .def("set_mode", &Localizer::set_mode, nb::arg("incremental"), nb::arg("parameters"))
        .def_prop_ro("incremental", &Localizer::incremental)
        .def("trigger_new_map", &Localizer::trigger_new_map)
        .def("node_pose", &Localizer::node_pose, nb::arg("id"))
        .def("add_link", &Localizer::add_link, nb::arg("source"), nb::arg("target"), nb::arg("transform"), nb::arg("variance"))
        .def("set_odometry_variance", &Localizer::set_odometry_variance, nb::arg("linear"), nb::arg("angular"))
        .def_prop_ro("nodes", &Localizer::nodes)
        .def_prop_ro("last_old_id", &Localizer::last_old_id)
        .def("close", &Localizer::close, nb::arg("save"));
}
