import { describe, expect, it } from 'vitest';

import { searchSlabs } from './search_slabs.ts';

describe('searchSlabs', () => {
  it.each([
    ['Why did the robot reboot?', 'brownout_and_gaps'],
    ['Did a wheel get blocked?', 'stall_events'],
    ['did the camera lose tracking', 'tracking_quality'],
    ['what uses the most power', 'power_budget'],
    ['is anything overheating', 'thermal_timeline'],
    ['compare the last two runs', 'run_compare'],
    ['did the robot almost hit something', 'obstacle_events'],
    ['what happened during the last mission', 'mission_timeline'],
    ['does the robot turn the way it is steered', 'steering_response'],
    ['average battery voltage in the last run', 'run_summary'],
    ['Jetson CPU frequency over time', 'jetson_throttling'],
    ['was there high ping or packet loss', 'wifi_health'],
    ['Was the robot throttled?', 'power_throttling'],
    ['were the Jetson clocks pinned', 'power_throttling'],
    ['why did the safety stop the robot', 'body_safety'],
    ['did the bumper hit something', 'body_safety'],
  ])('ranks %s to %s', (question, slab) => {
    expect(searchSlabs(question, 3).map((hit) => hit.slab)).toContain(slab);
  });
});
