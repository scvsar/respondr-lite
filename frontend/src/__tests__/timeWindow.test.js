import {timeWindowUrl} from '../timeWindow';

test('every time window produces the expected UTC cutoff',()=>{
  const now=Date.parse('2026-01-10T12:00:00Z');
  for(const [range,hours] of Object.entries({'1h':1,'6h':6,'12h':12,'24h':24,'3d':72,'7d':168})) {
    const url=new URL(timeWindowUrl('/api/current-status',range,'',now),'https://example.test');
    expect(Date.parse(url.searchParams.get('since'))).toBe(now-hours*3600000);
  }
});

test('an incomplete custom window cannot request all history',()=>{
  expect(timeWindowUrl('/api/current-status','custom','')).toBeNull();
  expect(timeWindowUrl('/api/current-status','custom','invalid-date')).toBeNull();
  expect(timeWindowUrl('/api/current-status','all')).toBe('/api/current-status');
});
