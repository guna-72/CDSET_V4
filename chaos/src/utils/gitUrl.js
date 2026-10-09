// Dependency-free URL helpers for the Git import UI (unit-testable with plain Node).
export const shortCommit = (c) => String(c || '').slice(0, 7);

// Accepts what people actually paste: "github.com/owner/repo", a browser URL
// like https://github.com/owner/repo/tree/dev/src, or a clone URL ending in
// .git. Returns the clean clone URL and (if the URL named one) the branch.
// The backend re-validates everything; this is for instant feedback only.
export function normalizeGitInput(rawUrl, rawBranch) {
  let url = String(rawUrl || '').trim();
  let branch = String(rawBranch || '').trim();
  if (url && !/^[a-z][a-z0-9+.-]*:/i.test(url) && /^[^\s/]+\.[^\s/]+\/[^\s/]+\/[^\s/]+/.test(url)) {
    url = `https://${url}`;
  }
  const tree = url.match(/^(https:\/\/[^/]+\/[^/]+\/[^/]+?)\/tree\/([^?#]+?)(?:\/.*)?$/i);
  if (tree) {
    url = tree[1];
    if (!branch) branch = decodeURIComponent(tree[2].split('/')[0]);
  }
  url = url.replace(/[?#].*$/, '').replace(/\/+$/, '');
  return { url, branch };
}

export function validateGitUrl(raw) {
  const url = String(raw || '').trim();
  if (!url) return 'Enter a repository URL.';
  if (/\s/.test(url)) return 'The URL must not contain spaces.';
  let u;
  try { u = new URL(url); } catch { return 'That is not a valid URL.'; }
  if (u.protocol !== 'https:') return 'Only public https:// repository URLs are supported.';
  if (u.username || u.password) return 'URLs with embedded credentials are not supported. Import a public repository, or download the ZIP and use the ZIP tab.';
  if (!u.hostname.includes('.')) return 'The URL needs a real host name, e.g. github.com.';
  if (u.pathname.split('/').filter(Boolean).length < 2) return 'Use the full repository URL, e.g. https://github.com/owner/repo';
  return '';
}
