import {vi} from 'vitest';
import React from 'react';
import {render,screen,waitFor,fireEvent,act} from '@testing-library/react';
import MobileView from '../MobileView';
import {apiGet} from '../api';
vi.mock('../api',()=>({apiGet:vi.fn()}));
vi.mock('../auth/msalClient',()=>({msalInstance:{logoutRedirect:vi.fn()}}));
const old={id:'old',user_id:'user-1',name:'Synthetic User',text:'Earlier',arrival_status:'Responding',vehicle:'POV',timestamp:'2026-01-01T00:00:00Z'};
const latest={...old,id:'new',text:'Current',vehicle:'Unknown',timestamp:'2026-01-01T01:00:00Z'};
function mockData(current=[latest], history=[old,latest]) {
  apiGet.mockImplementation(async path=>{
    if(path==='/api/user')return {authenticated:true};
    if(path==='/api/config')return {};
    if(path.startsWith('/api/current-status'))return current;
    if(path.startsWith('/api/responders'))return history;
    throw new Error('Unexpected request');
  });
}
beforeEach(()=>{vi.clearAllMocks();sessionStorage.clear();mockData();});

test.each([null, {rows: []}, [null], [{name: {invalid: true}}]])('malformed mobile response shows a clear error: %p', async payload => {
  mockData(payload);
  render(<MobileView/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid responder response');
  expect(screen.queryByText('Synthetic User')).not.toBeInTheDocument();
});

test('mobile uses current status and preserves unknown vehicle',async()=>{
  render(<MobileView/>);
  await screen.findByText('Synthetic User');
  expect(apiGet).toHaveBeenCalledWith(expect.stringContaining('/api/current-status?since='));
  expect(document.querySelector('.mobile-vehicle')).toHaveTextContent('Unknown');
});

test('latest cancellation hides an earlier response',async()=>{
  mockData([{...latest,arrival_status:'Cancelled'}],[old,{...latest,arrival_status:'Cancelled'}]);
  render(<MobileView/>);
  await screen.findByText('No responders yet.');
  expect(screen.queryByText('Synthetic User')).not.toBeInTheDocument();
});

test('different source users with the same name remain separate',async()=>{
  mockData([latest,{...latest,id:'other',user_id:'user-2'}]);
  render(<MobileView/>);
  await waitFor(()=>expect(screen.getAllByText('Synthetic User')).toHaveLength(2));
});

test('mobile does not request data after a failed auth check',async()=>{
  apiGet.mockRejectedValue(new Error('Sign-in check failed'));
  render(<MobileView/>);
  await screen.findByRole('alert');
  expect(apiGet.mock.calls.some(([path])=>path.startsWith('/api/responders')||path.startsWith('/api/current-status'))).toBe(false);
});

test('older time-range responses cannot replace the latest mobile result',async()=>{
  let release;
  const pending=new Promise(resolve=>{release=resolve;});
  apiGet.mockImplementation(async path=>{
    if(path==='/api/user')return {authenticated:true};
    if(path==='/api/config')return {};
    if(path.includes('since='))return pending;
    return [{...latest,name:'Latest Range User'}];
  });
  render(<MobileView/>);
  await waitFor(()=>expect(apiGet.mock.calls.some(([path])=>path.includes('since='))).toBe(true));
  fireEvent.change(screen.getByLabelText('Message time window'),{target:{value:'all'}});
  await screen.findByText('Latest Range User');
  await act(async()=>release([{...old,name:'Obsolete Range User'}]));
  expect(screen.getByText('Latest Range User')).toBeInTheDocument();
  expect(screen.queryByText('Obsolete Range User')).not.toBeInTheDocument();
});

test('custom window waits for a start time rather than loading all history',async()=>{
  render(<MobileView/>);
  await screen.findByText('Synthetic User');
  apiGet.mockClear();
  fireEvent.change(screen.getByLabelText('Message time window'),{target:{value:'custom'}});
  await screen.findByText('Choose a valid start time.');
  expect(apiGet).not.toHaveBeenCalled();
});
