// Run with:  node src/utils/gitUrl.test.mjs
import { normalizeGitInput as n, validateGitUrl as v, shortCommit } from './gitUrl.js';
import assert from 'node:assert/strict';
const eq=(a,b)=>assert.deepEqual(a,b);
eq(n('github.com/octocat/Hello-World',''),{url:'https://github.com/octocat/Hello-World',branch:''});
eq(n('  https://github.com/o/r.git  ',' dev '),{url:'https://github.com/o/r.git',branch:'dev'});
eq(n('https://github.com/o/r/tree/feature/x/src',''),{url:'https://github.com/o/r',branch:'feature'});
eq(n('https://github.com/o/r/tree/main',''),{url:'https://github.com/o/r',branch:'main'});
eq(n('https://github.com/o/r/tree/main','release'),{url:'https://github.com/o/r',branch:'release'});
eq(n('https://github.com/o/r/?tab=readme#x',''),{url:'https://github.com/o/r',branch:''});
eq(n('https://github.com/o/r/',''),{url:'https://github.com/o/r',branch:''});
eq(n('ssh://git@github.com/o/r',''),{url:'ssh://git@github.com/o/r',branch:''});   // not "fixed": stays invalid
for (const ok of ['https://github.com/o/r','https://github.com/o/r.git','https://gitlab.com/g/s/p']) eq(v(ok),'');
for (const bad of ['','  ','http://github.com/o/r','ssh://git@github.com/o/r','https://u:p@github.com/o/r','https://user@github.com/o/r','https://github.com/o','https://localhost/o/r','not a url','https://github.com/o/ r','git@github.com:o/r.git','file:///etc'])
  assert.notEqual(v(bad),'',`should reject ${bad}`);
eq(shortCommit('7fd1a60b01f91b314f'),'7fd1a60'); eq(shortCommit(null),'');
console.log('gitUrl.js: all assertions passed');
