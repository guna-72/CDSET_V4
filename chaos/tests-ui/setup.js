const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://localhost/', pretendToBeVisual: true });
const w = dom.window;
global.window = w; global.document = w.document; global.localStorage = w.localStorage;
for (const k of ['HTMLElement','Node','MutationObserver','Event','MouseEvent','KeyboardEvent','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','HTMLInputElement','SVGElement','Element','CustomEvent','DOMParser'])
  if (!(k in global) || k==='Node') try { global[k] = w[k]; } catch {}
try { Object.defineProperty(global,'navigator',{value:w.navigator,configurable:true}); } catch {}
w.matchMedia = w.matchMedia || (() => ({ matches:false, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){} }));
global.matchMedia = w.matchMedia;
class IO { observe(){} unobserve(){} disconnect(){} } global.IntersectionObserver = w.IntersectionObserver = IO; global.ResizeObserver = w.ResizeObserver = IO;
global.IS_REACT_ACT_ENVIRONMENT = true;
