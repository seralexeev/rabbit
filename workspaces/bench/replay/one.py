import sys
args, sys.argv = sys.argv[1:], sys.argv[:1]
import replay
from replay import *
sys.path.insert(0, "/private/tmp/claude-501/-Users-sergey-projects-rabbit/cd0fbbe7-7764-42de-a195-a98d0184779f/scratchpad")
from draw import draw
from lib.planner import Path as PPath, Waypoint, build_costmap
import duckdb
def run(trip, seconds=150, out=None):
    db = duckdb.connect(); db.execute("set TimeZone = 'UTC'"); db.execute(f"set file_search_path = '{export_dir()}'")
    for row in trips(db):
        if trip in row[0]:
            trip_id, t0, t1, phase, msg, replans, recoveries, kind, label, tx, tz, preview, length, plan_ms = row
            break
    origin, res, clearance = grid_for(map_at(str(t0)[:19])[1])
    camera, theta = start_pose(db, t0)
    rear = rear_pose(camera, theta)
    world = world_from(clearance, origin, res)
    sim = Sim(world, world, Robot(rear.x, rear.z, rear.theta))
    sim.costmap = costmap_from_clearance(origin, res, clearance)
    target = target_of(db, trip_id, kind, label, tx, tz)
    state = sim.run(target, seconds, trip_id)
    print(state["phase"], state["message"], state["events"])
    if out:
        tr = PPath([Waypoint(x, z, 0, 1) for x, z, _ in sim.trajectory], 0, 0, 0, 0)
        planned = [m for m in sim.messages if m[1].endswith("mission")]
        paths = [tr] + [PPath([Waypoint(p[0], p[1], 0, int(p[2])) for p in m[2]["steps"][0]["points"]], 0, 0, 0, 0) for m in planned[:3]]
        draw(sim.costmap, paths, out, [(tx, tz, (255, 0, 0)), (camera[0], camera[1], (255, 0, 255))], scale=6, room_r=sim.costmap.collision_radius)
    return sim
if __name__ == "__main__":
    if args and args[0] in DAYS:
        replay.DAY = args.pop(0)
    run(args[0] if args else "124929", out=str(OUT / "one.png"))
