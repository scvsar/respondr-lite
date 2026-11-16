// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom/vitest';
import {randomFillSync, webcrypto} from 'node:crypto';
import {cleanup} from '@testing-library/react';
import {afterEach} from 'vitest';
afterEach(cleanup);

// Polyfill crypto for MSAL
Object.defineProperty(global, 'crypto', {
  value: {
    getRandomValues: (arr) => randomFillSync(arr),
    subtle: webcrypto.subtle,
  },
});

// Polyfill TextEncoder/TextDecoder if needed (usually needed for MSAL too)
import { TextEncoder, TextDecoder } from 'util';
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// Set up global test environment
global.IS_REACT_ACT_ENVIRONMENT = true;
