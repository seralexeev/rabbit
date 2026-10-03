#include <rtabmap/core/CameraModel.h>
#include <rtabmap/core/Memory.h>
#include <rtabmap/core/Parameters.h>
#include <rtabmap/core/Rtabmap.h>
#include <rtabmap/core/SensorData.h>
#include <rtabmap/core/Signature.h>
#include <rtabmap/core/Statistics.h>
#include <rtabmap/utilite/ULogger.h>

#include <opencv2/imgcodecs.hpp>

#include <sys/resource.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

using rtabmap::Transform;

struct Args {
    std::string dump, odom, db, out, mode = "mapping";
    double rate = 2.0;
    double linVar = 1e-4, angVar = 1e-4;
    bool fresh = false;
    long startNs = 0, endNs = 0;
    rtabmap::ParametersMap params;
};

static void usage() {
    std::cerr << "rtab_run --dump DIR --odom TUM.txt --db MAP.db --out PREFIX [--mode mapping|localization]\n"
                 "         [--rate HZ] [--fresh] [--lin-var V] [--ang-var V] [--start-ns T] [--end-ns T]\n"
                 "         [--param Key=Value]...\n";
    std::exit(2);
}

static Args parse(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        auto next = [&]() -> std::string { if (i + 1 >= argc) usage(); return argv[++i]; };
        if (k == "--dump") a.dump = next();
        else if (k == "--odom") a.odom = next();
        else if (k == "--db") a.db = next();
        else if (k == "--out") a.out = next();
        else if (k == "--mode") a.mode = next();
        else if (k == "--rate") a.rate = std::stod(next());
        else if (k == "--lin-var") a.linVar = std::stod(next());
        else if (k == "--ang-var") a.angVar = std::stod(next());
        else if (k == "--start-ns") a.startNs = std::stol(next());
        else if (k == "--end-ns") a.endNs = std::stol(next());
        else if (k == "--fresh") a.fresh = true;
        else if (k == "--param") {
            std::string kv = next();
            auto p = kv.find('=');
            if (p == std::string::npos) usage();
            a.params[kv.substr(0, p)] = kv.substr(p + 1);
        } else usage();
    }
    if (a.dump.empty() || a.odom.empty() || a.db.empty() || a.out.empty()) usage();
    if (a.mode != "mapping" && a.mode != "localization") usage();
    return a;
}

static double jsonNumber(const std::string& text, const std::string& key) {
    std::smatch m;
    std::regex re("\"" + key + "\":\\s*([-0-9.eE]+)");
    if (!std::regex_search(text, m, re)) throw std::runtime_error("meta.json: no " + key);
    return std::stod(m[1]);
}

static std::map<long, Transform> loadTum(const std::string& path) {
    std::map<long, Transform> poses;
    std::ifstream f(path);
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream s(line);
        double t, x, y, z, qx, qy, qz, qw;
        if (!(s >> t >> x >> y >> z >> qx >> qy >> qz >> qw)) continue;
        poses[std::llround(t * 1e9)] = Transform(x, y, z, qx, qy, qz, qw);
    }
    return poses;
}

static Transform nearest(const std::map<long, Transform>& poses, long t, long tol) {
    auto it = poses.lower_bound(t);
    long best = tol + 1;
    Transform out;
    if (it != poses.end() && std::labs(it->first - t) < best) { best = std::labs(it->first - t); out = it->second; }
    if (it != poses.begin()) {
        --it;
        if (std::labs(it->first - t) < best) out = it->second;
    }
    return out;
}

static double rssMb() {
    std::ifstream f("/proc/self/status");
    std::string line;
    while (std::getline(f, line))
        if (line.rfind("VmRSS:", 0) == 0) return std::stod(line.substr(6)) / 1024.0;
    return 0;
}

static std::string tum(double t, const Transform& p) {
    Eigen::Quaternionf q = p.getQuaternionf();
    char buf[256];
    std::snprintf(buf, sizeof(buf), "%.9f %.5f %.5f %.5f %.6f %.6f %.6f %.6f", t, p.x(), p.y(), p.z(), q.x(), q.y(),
                  q.z(), q.w());
    return buf;
}

static double percentile(std::vector<double> v, double p) {
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    return v[std::min(v.size() - 1, static_cast<size_t>(p * v.size()))];
}

int main(int argc, char** argv) {
    Args a = parse(argc, argv);
    ULogger::setType(ULogger::kTypeConsole);
    ULogger::setLevel(ULogger::kWarning);

    std::ifstream metaFile(a.dump + "/meta.json");
    std::string meta((std::istreambuf_iterator<char>(metaFile)), std::istreambuf_iterator<char>());
    const Transform optical = rtabmap::CameraModel::opticalRotation();
    rtabmap::CameraModel model(jsonNumber(meta, "fx"), jsonNumber(meta, "fy"), jsonNumber(meta, "cx"),
                               jsonNumber(meta, "cy"), optical, 0,
                               cv::Size(jsonNumber(meta, "width"), jsonNumber(meta, "height")));

    auto odom = loadTum(a.odom);
    if (odom.empty()) { std::cerr << "no odometry poses in " << a.odom << "\n"; return 1; }

    const bool localization = a.mode == "localization";
    rtabmap::ParametersMap params;
    params[rtabmap::Parameters::kRtabmapTimeThr()] = "0";
    params[rtabmap::Parameters::kRtabmapMemoryThr()] = "0";
    params[rtabmap::Parameters::kMemIncrementalMemory()] = localization ? "false" : "true";
    params[rtabmap::Parameters::kMemInitWMWithAllNodes()] = localization ? "true" : "false";
    if (localization) {
        params[rtabmap::Parameters::kRGBDLinearUpdate()] = "0";
        params[rtabmap::Parameters::kRGBDAngularUpdate()] = "0";
    }
    for (auto& kv : a.params) params[kv.first] = kv.second;

    if (a.fresh) std::remove(a.db.c_str());
    rtabmap::Rtabmap rtab;
    rtab.init(params, a.db);
    const int lastOldId = rtab.getLastLocationId();

    std::ofstream csv(a.out + ".csv");
    csv << "t_ns,id,process_ms,total_ms,loop_id,proximity_id,inter_session,highest_hyp_id,highest_hyp_value,"
           "rejected,inliers,wm_size,rss_mb,map_x,map_y,map_z,corr_norm,corr_yaw_deg\n";
    std::ofstream poses(a.out + "_poses.txt");

    std::ifstream frames(a.dump + "/frames.csv");
    std::string line;
    std::getline(frames, line);
    long lastNs = 0;
    int id = 0, processed = 0, noOdom = 0, matched = 0, interSession = 0;
    long firstNs = 0, firstMatchNs = 0;
    std::vector<double> times;
    const long period = static_cast<long>(1e9 / a.rate);
    const auto wall0 = std::chrono::steady_clock::now();
    while (std::getline(frames, line)) {
        std::vector<std::string> c;
        std::stringstream ss(line);
        std::string item;
        while (std::getline(ss, item, ',')) c.push_back(item);
        if (c.size() < 6 || c[4].empty() || c[5].empty()) continue;
        long t = std::stol(c[0]);
        if (a.startNs && t < a.startNs) continue;
        if (a.endNs && t > a.endNs) break;
        if (lastNs && t - lastNs < period) continue;
        Transform odomOpt = nearest(odom, t, 20'000'000);
        if (odomOpt.isNull()) { ++noOdom; continue; }
        lastNs = t;
        if (!firstNs) firstNs = t;
        Transform odomBase = optical * odomOpt * optical.inverse();

        cv::Mat rgb = cv::imread(a.dump + "/" + c[4], cv::IMREAD_COLOR);
        cv::Mat depth = cv::imread(a.dump + "/" + c[5], cv::IMREAD_ANYDEPTH);
        rtabmap::SensorData data(rgb, depth, model, ++id, t / 1e9);

        auto t0 = std::chrono::steady_clock::now();
        rtab.process(data, odomBase, a.linVar, a.angVar);
        double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        times.push_back(ms);
        ++processed;

        const rtabmap::Statistics& st = rtab.getStatistics();
        const auto& d = st.data();
        auto stat = [&](const std::string& k) { auto it = d.find(k); return it == d.end() ? 0.f : it->second; };
        int loop = st.loopClosureId(), prox = st.proximityDetectionId();
        int match = loop ? loop : prox;
        bool inter = !localization && match > 0 && match <= lastOldId;
        if (match) { ++matched; if (!firstMatchNs) firstMatchNs = t; }
        if (inter) ++interSession;

        Transform corr = rtab.getMapCorrection();
        Transform mapOpt = optical.inverse() * (corr * odomBase) * optical;
        poses << tum(t / 1e9, mapOpt) << "\n";
        char buf[512];
        std::snprintf(buf, sizeof(buf), "%ld,%d,%.1f,%.1f,%d,%d,%d,%d,%.3f,%d,%d,%d,%.0f,%.3f,%.3f,%.3f,%.3f,%.2f\n",
                      t, id, ms, stat(rtabmap::Statistics::kTimingTotal()), loop, prox, inter ? 1 : 0,
                      static_cast<int>(stat(rtabmap::Statistics::kLoopHighest_hypothesis_id())),
                      stat(rtabmap::Statistics::kLoopHighest_hypothesis_value()),
                      static_cast<int>(stat(rtabmap::Statistics::kLoopRejectedHypothesis())),
                      static_cast<int>(stat(rtabmap::Statistics::kLoopVisual_inliers())), rtab.getWMSize(), rssMb(),
                      mapOpt.x(), mapOpt.y(), mapOpt.z(), corr.getNorm(), corr.theta() * 180 / M_PI);
        csv << buf;
        if (processed % 50 == 0)
            std::cerr << processed << " frames, " << matched << " matched, p50 " << percentile(times, 0.5) << " ms\n";
    }
    double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall0).count();

    if (!localization) {
        std::map<int, Transform> graph;
        std::multimap<int, rtabmap::Link> links;
        std::map<int, rtabmap::Signature> sigs;
        rtab.getGraph(graph, links, true, true, &sigs, false, false, false, false, false, false);
        std::ofstream g(a.out + "_graph.txt");
        for (auto& [nid, p] : graph) {
            auto s = sigs.find(nid);
            if (s == sigs.end()) continue;
            g << tum(s->second.getStamp(), optical.inverse() * p * optical) << " " << nid << " "
              << s->second.mapId() << "\n";
        }
        int loops = 0;
        for (auto& [from, l] : links)
            if (l.type() == rtabmap::Link::kGlobalClosure || l.type() == rtabmap::Link::kLocalSpaceClosure) ++loops;
        std::cerr << "graph: " << graph.size() << " nodes, " << loops << " loop links\n";
    }

    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    double cpu = ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
    std::ofstream js(a.out + "_summary.json");
    js << "{\n  \"mode\": \"" << a.mode << "\",\n  \"rate_hz\": " << a.rate << ",\n  \"processed\": " << processed
       << ",\n  \"no_odom\": " << noOdom << ",\n  \"matched\": " << matched
       << ",\n  \"inter_session\": " << interSession << ",\n  \"first_match_s\": "
       << (firstMatchNs ? (firstMatchNs - firstNs) / 1e9 : -1) << ",\n  \"process_ms_p50\": " << percentile(times, 0.5)
       << ",\n  \"process_ms_p95\": " << percentile(times, 0.95) << ",\n  \"process_ms_max\": "
       << percentile(times, 1.0) << ",\n  \"wall_s\": " << wall << ",\n  \"cpu_s\": " << cpu
       << ",\n  \"max_rss_mb\": " << ru.ru_maxrss / 1024.0 << ",\n  \"wm_size\": " << rtab.getWMSize()
       << ",\n  \"old_last_id\": " << lastOldId << "\n}\n";
    js.close();
    rtab.close(!localization);
    std::ifstream in(a.out + "_summary.json");
    std::cout << in.rdbuf();
    return 0;
}
