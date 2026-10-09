// Turns raw technical errors (Windows error codes, stack-trace lines, HTTP
// statuses, Node/Python startup errors) into plain sentences a normal user can
// act on. Anything we do not recognise is returned UNCHANGED, so a real backend
// message is never hidden or replaced by a wrong guess.
//
//   friendlyError(err)        -> string (safe to show in the UI)
//   friendlyErrorParts(err)   -> { message, detail }  detail = original text, or '' if unchanged

// Language names for compiler messages
const LANG_BY_TOOL = { javac: 'Java', java: 'Java', 'g++': 'C++', gcc: 'C', rustc: 'Rust', kotlinc: 'Kotlin' };

// Shorten one line of compiler output
function firstErrLine(text) {
  const lines = String(text || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  return (lines.find(l => /error|exception|panic|fatal/i.test(l)) || lines[0] || '').slice(0, 220);
}

// "javac failed to build Main.java (exited 1): <compiler output>"  ->  language + translated first problem
function compileFailed(m) {
  const lang = LANG_BY_TOOL[m[1]] || m[1];
  const body = m[3] || '';
  const inner = friendlyErrorParts(body);
  const why = inner.recognised ? inner.message : `First error: ${firstErrLine(body) || 'see the backend window'}`;
  const timedOut = /timed out/i.test(m[2] || '');
  return timedOut
    ? `The ${lang} build took too long and was stopped, so the test did not start. Check for endless loops or huge files.`
    : `The ${lang} code could not be compiled, so the test did not start. ${why}`;
}

// "project execution_status is X — cannot run experiments ...: <reason> (after fixing it, ...)"
function blockedProject(m) {
  const reason = (m[1] || '').trim();
  const inner = friendlyErrorParts(reason);
  const why = inner.recognised ? inner.message : reason;
  return `Tests cannot run on this project yet. ${why} After fixing it, click Re-analyze.`;
}

const RULES = [

  // ======== LANGUAGE-SPECIFIC ERRORS (Python, Node, Java, C, C++, Go, Rust, Kotlin, PHP, Ruby, React) ========
  // Kept first so a language's own message is never swallowed by a broader rule below.

  // ---- Tool / runtime not installed (any language, Windows + Linux) -------
  [/'([\w.+-]+)' is not recognized as an internal or external command/i,
    (m) => `The program "${m[1]}" is not installed or not on PATH. Install it, restart the backend, and try again.`],
  [/([\w.+-]+): command not found/i,
    (m) => `The program "${m[1]}" is not installed or not on PATH. Install it, restart the backend, and try again.`],
  [/is not recognized as the name of a cmdlet/i,
    'A needed program is not installed or not on PATH. Install it, restart the backend, and try again.'],
  [/Python was not found; run without arguments|python(3)?\.exe.*Microsoft Store/i,
    'Python is not installed (Windows only has a Store shortcut). Install Python from python.org, tick "Add to PATH", and restart the backend.'],
  [/FileNotFoundError: \[WinError 2\]|\[Errno 2\] No such file or directory: '(javac|java|gcc|g\+\+|node|npm|go|rustc|kotlinc|php|ruby|python3?|git)'/i,
    'A program needed to run this project (compiler or runtime) is not installed or not on PATH. Install it, restart the backend and click Re-analyze.'],
  [/(javac\/java|javac|java) not found on PATH/i,
    'Java is missing. Install a JDK (not only a JRE), restart the backend, then click Re-analyze.'],
  [/(g\+\+|gcc)(\/[\w+]+)* not found on PATH/i,
    'A C/C++ compiler is missing. Install MinGW-w64 or MSYS2 (gcc/g++), add it to PATH, restart the backend, then click Re-analyze.'],
  [/\bgo(\/[\w+]+)* not found on PATH/i,
    'Go is missing. Install the Go toolchain from go.dev, restart the backend, then click Re-analyze.'],
  [/rustc not found on PATH/i,
    'Rust is missing. Install Rust from rustup.rs, restart the backend, then click Re-analyze.'],
  [/kotlinc not found on PATH/i,
    'The Kotlin compiler is missing. Install kotlinc, add it to PATH, restart the backend, then click Re-analyze.'],
  [/\bphp(\/[\w+]+)* not found on PATH/i,
    'PHP is missing. Install PHP, add it to PATH, restart the backend, then click Re-analyze.'],
  [/\bruby(\/[\w+]+)* not found on PATH/i,
    'Ruby is missing. Install Ruby, add it to PATH, restart the backend, then click Re-analyze.'],

  // ---- Why a project is blocked (analyzer reasons) -------------------------
  [/execution_status is \w+ — cannot run experiments[^:]*:\s*([\s\S]*?)\s*\(after fixing it/i, blockedProject],
  [/no code path reading the PORT environment variable/i,
    'This project listens on a fixed port. Make it read the PORT variable (Python: os.environ.get("PORT", 5000), Node: process.env.PORT || 3000) so tests can reach it, then Re-analyze.'],
  [/dependency not importable in this sandbox|dependencies? (\[.*\] )?that aren't installed/i,
    'The project needs packages that are not installed here. Install them on this computer (pip install / npm install), then click Re-analyze.'],
  [/Django execution adapter is out of MVP scope/i,
    'Django projects can be analysed but not run by chaos tests yet.'],
  [/Streamlit app .* no execution adapter/i,
    'Streamlit apps can be analysed but not run by chaos tests yet.'],
  [/Frontend framework, not an HTTP service/i,
    'React / Next.js projects can be analysed but not chaos-tested, because they are not a server. Test their backend API instead.'],

  // ---- Compile / build failed (wraps the real compiler message) ------------
  [/(javac|g\+\+|gcc|rustc|kotlinc) failed to build \S+ \(([^)]*)\):\s*([\s\S]*)/i, compileFailed],

  // ---- Exit codes / crashes of native programs ------------------------------
  [/Floating point exception|SIGFPE/i,
    'The program divided by zero and crashed. Check the divisor before dividing.'],
  [/0xC0000005|3221225477|Segmentation fault|SIGSEGV|exit(ed)?( with)?( code)? 139\b/i,
    'The program touched memory it does not own and crashed (segmentation fault / access violation). Check array indexes, null pointers and freed memory.'],
  [/0xC00000FD|3221225725/i,
    'The program called itself endlessly until the stack was full (stack overflow). Add a stopping condition to the recursion.'],
  [/stack smashing detected|buffer overflow detected|0xC0000409|3221226505/i,
    'The program wrote past the end of an array or buffer and was stopped. Check array sizes and string copies.'],
  [/double free|free\(\): invalid|munmap_chunk|corrupted (size|double-linked)|heap corruption|0xC0000374/i,
    'The program freed memory twice or damaged the heap. Check every free/delete and pointer use.'],
  [/exit(ed)?( with)?( code)? 137\b|SIGKILL|\bKilled\b/,
    'The program was force-stopped (usually out of memory or stopped by the safety timer). Check for endless loops or huge data.'],
  [/Aborted \(core dumped\)|^Aborted$|SIGABRT|exit(ed)?( with)?( code)? 134\b/m,
    'The program aborted itself. Look for a failed assert(), an uncaught exception or a memory error.'],

  // ---- Java ------------------------------------------------------------------
  [/cannot find symbol(?:[\s\S]*?symbol:\s*(?:variable|method|class)\s+([\w.$]+))?/i,
    (m) => m[1] ? `Java cannot find "${m[1]}". Check the spelling, that it is declared before use, and that the import line is present.` : 'Java cannot find a name used in the code. Check spelling, declarations and imports.'],
  [/error: '([^']+)' expected/i,
    (m) => `Java expected "${m[1]}" here. A semicolon, bracket or similar is missing on or just before that line.`],
  [/class (\w+) is public, should be declared in a file named/i,
    (m) => `The public class "${m[1]}" must be inside a file named ${m[1]}.java. Rename the file or the class.`],
  [/incompatible types: (.+)/i,
    (m) => `Java types do not match (${m[1].slice(0, 100)}). Convert the value or change the variable type.`],
  [/missing return statement/i,
    'A Java method that must return a value has a path with no return. Add a return at the end.'],
  [/package ([\w.]+) does not exist/i,
    (m) => `The Java package "${m[1]}" is not available. Only the standard library works here (plain javac, no Maven/Gradle downloads).`],
  [/reached end of file while parsing|class, interface, or enum expected|illegal start of (expression|type)/i,
    'Java brackets do not match: a closing } is missing or there is an extra one. Check the code near the end of the file.'],
  [/unreported exception ([\w.]+)/i,
    (m) => `Java requires ${m[1]} to be handled. Wrap the call in try/catch or add "throws ${m[1]}" to the method.`],
  [/variable (\w+) might not have been initialized/i,
    (m) => `The Java variable "${m[1]}" is used before it gets a value. Give it an initial value.`],
  [/Could not find or load main class ([\w.$]+)/i,
    (m) => `Java could not start "${m[1]}". The file name and class name must match, and the class needs a main method.`],
  [/Main method not found|no main manifest attribute|Error: Main method/i,
    'The program has no main method to start from. Add public static void main(String[] args) (Kotlin: fun main()).'],
  [/java\.lang\.NullPointerException|NullPointerException/i,
    'The program used an empty (null) object and crashed. Check that the object is created before calling its methods.'],
  [/ArrayIndexOutOfBoundsException|StringIndexOutOfBoundsException|IndexOutOfBoundsException/i,
    'The program read a position that does not exist in an array, string or list. Check the index and the length.'],
  [/ArithmeticException: \/ by zero/i,
    'The program divided by zero. Check the divisor before dividing.'],
  [/NumberFormatException: (?:For input string: )?(.+)/i,
    (m) => `The program tried to turn ${m[1]} into a number, but it is not a valid number.`],
  [/InputMismatchException|NoSuchElementException: No line found|NoSuchElementException/i,
    'The program asked for input but got none or the wrong kind. Type the input in the "Program input" box before running.'],
  [/ClassCastException/i,
    'The program treated an object as the wrong type. Check the cast.'],
  [/ConcurrentModificationException/i,
    'A list was changed while it was being looped over. Loop over a copy, or use an iterator.'],
  [/ClassNotFoundException|NoClassDefFoundError/i,
    'Java could not find a class it needs. Check the class name and that every needed class file was compiled.'],
  [/UnsupportedClassVersionError/i,
    'The code was compiled with a newer Java than the one running it. Use the same Java version for compiling and running.'],

  // ---- C / C++ ---------------------------------------------------------------
  [/undefined reference to [`']?(main|WinMain|wmain)'?/i,
    'The program has no main() function to start from. Add int main() to the entry file.'],
  [/undefined reference to [`']([^'`]+)'/i,
    (m) => `The program uses "${m[1]}" but it is never defined or its library is not linked. Only the entry file is compiled, so code in other .c/.cpp files is not included.`],
  [/fatal error: ([^:\s]+): No such file or directory/i,
    (m) => `The header "${m[1]}" was not found. Check the file name, or it belongs to a library that is not installed here.`],
  [/'([^']+)' was not declared in this scope|error: '([^']+)' undeclared/i,
    (m) => `"${m[1] || m[2]}" is used before it is declared. Declare it first or add the right #include.`],
  [/implicit declaration of function '?(\w+)'?/i,
    (m) => `The function "${m[1]}" is used without being declared. Add the #include that provides it.`],
  [/error: expected '([^']+)' before/i,
    (m) => `A "${m[1]}" is missing near the line shown. Check for a missing semicolon or bracket just before it.`],
  [/multiple definition of/i,
    'The same function or variable is defined twice. Keep one definition (put declarations in headers).'],
  [/terminate called after throwing an instance of '([^']+)'/i,
    (m) => `The C++ program threw an uncaught ${m[1]} error and stopped. Check the values used, or wrap the code in try/catch.`],

  // ---- Go --------------------------------------------------------------------
  [/declared (?:and|but) not used:? ?(\w+)?/i,
    (m) => `Go does not allow unused variables${m[1] ? ` ("${m[1]}")` : ''}. Use it or delete it.`],
  [/"([^"]+)" imported and not used/i,
    (m) => `Go does not allow unused imports ("${m[1]}"). Remove the import or use the package.`],
  [/(?:^|\s)undefined: (\w+)/i,
    (m) => `Go does not know "${m[1]}". Check the spelling, that it is declared, and that its package is imported.`],
  [/go\.mod file not found|no required module provides package ([^;\s]+)|missing go\.sum entry/i,
    (m) => `Go cannot find the package${m[1] ? ` "${m[1]}"` : ''} it needs. Outside packages cannot be downloaded here, so use only the standard library or add go.mod and vendor the packages.`],
  [/package ([\w./-]+) is not in (std|GOROOT)/i,
    (m) => `"${m[1]}" is not a standard Go package. Check the import path.`],
  [/panic: runtime error: index out of range/i,
    'The Go program read a slice/array position that does not exist. Check the index and the length.'],
  [/invalid memory address or nil pointer dereference/i,
    'The Go program used a nil pointer. Check that it is set before use.'],
  [/all goroutines are asleep - deadlock/i,
    'The Go program is stuck: every goroutine is waiting. Check channels and locks (something sends or receives with no partner).'],
  [/concurrent map (writes|read and map write)/i,
    'Several goroutines used one map at the same time. Protect the map with a sync.Mutex.'],
  [/cannot use (.+?) as (.+?) value/i,
    (m) => `Go types do not match: ${m[1].slice(0, 60)} cannot be used as ${m[2].slice(0, 40)}. Convert it or change the type.`],
  [/syntax error: (.+)/,
    (m) => `Go syntax mistake (${m[1].slice(0, 100)}). Check brackets, commas and the line above.`],
  [/panic: (.+)/,
    (m) => `The Go program panicked: ${m[1].slice(0, 150)}`],

  // ---- Rust ------------------------------------------------------------------
  [/can't find crate for `([^`]+)`|error\[E0463\]/i,
    (m) => { const n = m[1] || (m.input.match(/`([^`]+)`/) || [])[1]; return `The Rust crate${n ? ` "${n}"` : ''} is not available. Only the standard library works here (no cargo downloads).`; }],
  [/unresolved import `([^`]+)`|error\[E0432\]|error\[E0433\]|failed to resolve: /i,
    (m) => { const n = m[1] || (m.input.match(/`([^`]+)`/) || [])[1]; return `Rust cannot find${n ? ` "${n}"` : ' an import'}. Check the "use" line and that the module exists.`; }],
  [/error\[E0425\]|cannot find (?:value|function) `([^`]+)`/i,
    (m) => { const n = m[1] || (m.input.match(/`([^`]+)`/) || [])[1]; return `Rust cannot find${n ? ` "${n}"` : ' a name'}. Check the spelling and that it is declared before use.`; }],
  [/error\[E0382\]|borrow of moved value|use of moved value/i,
    'A Rust value was used after being moved. Clone it (.clone()) or borrow it with & instead.'],
  [/error\[E0308\]|mismatched types/i,
    'Rust types do not match. Convert the value (for example .to_string() or "as") or fix the declared type.'],
  [/error\[E0599\]|no method named `([^`]+)`/i,
    (m) => { const n = m[1] || (m.input.match(/`([^`]+)`/) || [])[1]; return `That Rust type has no method${n ? ` "${n}"` : ''}. Check the spelling and the type.`; }],
  [/error\[E0502\]|error\[E0499\]|cannot borrow/i,
    'Rust does not allow this borrow: a value is used mutably and read at the same time. Split the steps or clone the value.'],
  [/error\[E0384\]|cannot assign twice to immutable variable/i,
    'This Rust variable cannot be changed. Declare it with "let mut".'],
  [/error\[E0601\]|`main` function not found/i,
    'The Rust program has no main function. Add fn main() to the entry file.'],
  [/called `Option::unwrap\(\)` on a `None` value/i,
    'The Rust program unwrapped an empty Option (None) and panicked. Use match or if let instead of unwrap().'],
  [/called `Result::unwrap\(\)` on an `Err` value|called `Result::expect\(\)`/i,
    'The Rust program unwrapped an error result and panicked. Handle the Err case instead of unwrap().'],
  [/attempt to divide by zero|attempt to calculate the remainder with a divisor of zero/i,
    'The Rust program divided by zero and panicked. Check the divisor first.'],
  [/attempt to (add|subtract|multiply) with overflow/i,
    (m) => `A Rust number overflowed while trying to ${m[1]}. Use a bigger type or checked_${m[1]}().`],
  [/index out of bounds: the len is (\d+) but the index is (\d+)/i,
    (m) => `The Rust program read position ${m[2]} but the list only has ${m[1]} items.`],
  [/thread '[^']*' panicked at/i,
    'The Rust program panicked (a deliberate crash on an unexpected situation). Read the line number in the message to find where.'],

  // ---- Kotlin ----------------------------------------------------------------
  [/unresolved reference:? ?([\w.]+)/i,
    (m) => `Kotlin cannot find "${m[1]}". Check the spelling, the declaration and the import.`],
  [/Type mismatch/i,
    'Kotlin types do not match. Convert the value or change the declared type.'],
  [/Val cannot be reassigned/i,
    'A Kotlin "val" cannot be changed. Declare it with "var" instead.'],
  [/Smart cast to '([^']+)' is impossible/i,
    (m) => `Kotlin cannot be sure this value is ${m[1]}. Store it in a local val first, or cast it explicitly.`],
  [/lateinit property (\w+) has not been initialized/i,
    (m) => `The Kotlin property "${m[1]}" was used before it was set. Assign it first.`],
  [/Null can not be a value of a non-null type/i,
    'Kotlin does not allow null here. Make the type nullable with ? or give a real value.'],
  [/kotlinc.*error: expecting|error: expecting /i,
    'Kotlin syntax mistake: something is missing near the line shown (bracket, parenthesis or keyword).'],

  [/Exception in thread "([^"]+)" ([\w.$]+)/i,
    (m) => `The Java program stopped with the error ${m[2].split('.').pop()}. Read the line number in the message to find where.`],

  // ---- PHP -------------------------------------------------------------------
  [/Parse error:\s*syntax error, (.+?)(?: in |$)/i,
    (m) => `PHP syntax mistake (${m[1].slice(0, 100)}). Check for a missing semicolon, bracket or quote on or just above that line.`],
  [/Call to undefined function (\w+)\(\)/i,
    (m) => `The PHP function "${m[1]}" does not exist. Check the spelling, or the PHP extension is not installed.`],
  [/Call to undefined method ([\w\\:]+)/i,
    (m) => `The PHP method "${m[1]}" does not exist. Check the class and method name.`],
  [/Class ['"]([^'"]+)['"] not found/i,
    (m) => `The PHP class "${m[1]}" was not found. Check the name and that its file is included (require).`],
  [/Undefined (variable|array key|index|offset):? ?\$?['"]?([^'"\s]+)/i,
    (m) => `PHP used the ${m[1]} "${m[2]}" before it exists. Set it first or check with isset().`],
  [/Allowed memory size of \d+ bytes exhausted/i,
    'The PHP program used too much memory. Check for endless loops or huge arrays.'],
  [/Maximum execution time of \d+ seconds exceeded/i,
    'The PHP program ran too long and was stopped. Check for endless loops.'],
  [/Failed opening required|Failed opening ['"]?[^'" ]+['"]? for inclusion|failed to open stream/i,
    'PHP could not open a file it tried to include or read. Check the file path (relative to the project folder).'],
  [/Division by zero|DivisionByZeroError/i,
    'The program divided by zero. Check the divisor before dividing.'],
  [/Uncaught (\w+): (.+?) in \S+:\d+/i,
    (m) => `The program stopped because of an uncaught ${m[1]}: ${m[2].slice(0, 120)}`],

  // ---- Ruby ------------------------------------------------------------------
  [/undefined method [`'‘]?([^'`’\s]+)['’]? for (nil|[^\n(]+)/i,
    (m) => /^nil/.test(m[2]) ? `The Ruby program called "${m[1]}" on nil (an empty value). Check that the value exists first.` : `The Ruby object has no method "${m[1]}". Check the spelling and the object type.`],
  [/undefined local variable or method [`'‘]?([^'`’\s]+)/i,
    (m) => `Ruby does not know "${m[1]}". Define it before use or check the spelling.`],
  [/cannot load such file -- (\S+)/i,
    (m) => `Ruby cannot load "${m[1]}". If it is a gem, install it (gem install); if it is your own file, check the require path.`],
  [/ArgumentError: wrong number of arguments \(given (\d+), expected ([^)]+)\)/i,
    (m) => `A Ruby method was called with ${m[1]} argument(s) but needs ${m[2]}.`],
  [/KeyError: key not found: (.+)/i,
    (m) => `The Ruby hash has no key ${m[1]}. Check the key or use fetch with a default.`],
  [/Errno::ENOENT/i,
    'The Ruby program tried to open a file that does not exist. Check the file path (relative to the project folder).'],
  [/SystemStackError|stack level too deep/i,
    'The Ruby program called itself endlessly (infinite recursion). Add a stopping condition.'],
  [/FrozenError/i,
    'The Ruby program tried to change a frozen (read-only) value. Work on a copy with dup.'],
  [/no implicit conversion of (\w+) into (\w+)|(?:String|nil) can't be coerced into (\w+)/i,
    'Ruby cannot mix these two types. Convert one of them (to_s, to_i).'],

  // ---- Python (more) -----------------------------------------------------------
  [/FileNotFoundError: \[Errno 2\] No such file or directory: ['"]?([^'"\n]+)/i,
    (m) => `The program tried to open "${m[1]}" but that file does not exist. Check the name and path (paths are relative to the project folder).`],
  [/EOFError/i,
    'The program waited for keyboard input (input()) but none was given. Type the input in the "Program input" box before running.'],
  [/ValueError: invalid literal for int\(\) with base \d+: (.+)/i,
    (m) => `The program tried to turn ${m[1]} into a whole number, but it is not one.`],
  [/ValueError: could not convert string to float: (.+)/i,
    (m) => `The program tried to turn ${m[1]} into a number, but it is not one.`],
  [/UnicodeDecodeError|UnicodeEncodeError/i,
    'A file has characters the program could not read. Open it with encoding="utf-8" (or the right encoding).'],
  [/TabError|inconsistent use of tabs and spaces/i,
    'The Python file mixes tabs and spaces for indentation. Use only spaces (4 per level).'],
  [/AssertionError/i,
    'An assert check in the program failed, so it stopped on purpose. The condition it checks was false.'],
  [/PermissionError: \[(Errno 13|WinError 5)\]/i,
    'The program was not allowed to open a file or folder. Check that it is not open elsewhere and is not read-only.'],
  [/Errno 98|Errno 10048|WinError 10048/i,
    'The project could not start because its port is already in use. Stop the other program using that port and try again.'],
  [/requests\.exceptions\.(ConnectionError|Timeout|ConnectTimeout|ReadTimeout)|urllib\.error\.URLError|urllib3\.exceptions/i,
    'The project tried to reach another server or website and could not (there is no internet inside the safety sandbox).'],
  [/Working outside of (application|request) context/i,
    'Flask code that needs an active request or app was run too early. Move it inside a route, or use "with app.app_context():".'],
  [/TemplateNotFound: (.+)/i,
    (m) => `Flask could not find the template "${m[1].trim()}". Put it in a "templates" folder next to the app.`],
  [/KeyboardInterrupt/i,
    'The program was stopped by hand (Ctrl+C or the Stop button).'],

  // ---- Node / JavaScript (more) --------------------------------------------
  [/Cannot find module '(\.{1,2}[\\/][^']*|[\\/][^']*)'/i,
    (m) => `The project imports the file "${m[1]}" but it does not exist. Check the file name, letter case and path.`],
  [/Cannot find package '([^']+)'/i,
    (m) => `The project needs the package "${m[1]}" but it is not installed. Add it to package.json, run npm install, then Re-analyze.`],
  [/ERR_REQUIRE_ESM|require\(\) of ES Module/i,
    'This project mixes require() and import. Use one style, or add "type": "module" to package.json.'],
  [/Cannot use import statement outside a module|require is not defined in ES module scope/i,
    'This project mixes require() and import. Use one style, or add "type": "module" to package.json.'],
  [/TypeError: ([^\n]+?) is not a function/i,
    (m) => `The project called ${m[1].slice(0, 60)} as a function, but it is not one. Check the name and what it really is.`],
  [/is not a constructor/i,
    'The project used "new" on something that is not a class. Check the import.'],
  [/Cannot set headers after they are sent|ERR_HTTP_HEADERS_SENT/i,
    'A route sent two responses to the same request. Add "return" after res.send()/res.json().'],
  [/\bENOTFOUND\b|\bgetaddrinfo\b/,
    'The project tried to reach a website that could not be found (wrong address, or no internet in the safety sandbox).'],
  [/EMFILE|too many open files/i,
    'The project opened too many files at once and ran out of file handles. Close files after use.'],
  [/ERR_INVALID_ARG_TYPE/i,
    'A function got the wrong type of value (for example undefined instead of text). Check what is passed in.'],
  [/npm (ERR!|error)/i,
    'An npm command failed. Run npm install in the project folder and read the first error line.'],

  // ---- React / Vite / Webpack (analysed, not run) -----------------------------
  [/Failed to resolve import ["']([^"']+)["']|Module not found: (?:Error: )?Can't resolve '([^']+)'/i,
    (m) => `The project imports "${m[1] || m[2]}" but it cannot be found. Check the file path or install the package.`],
  [/Invalid hook call/i,
    'A React hook was used in the wrong place. Hooks only work at the top of a function component, not in loops, conditions or normal functions.'],
  [/Objects are not valid as a React child/i,
    'React tried to show an object as text. Show one of its fields (for example {user.name}) instead of the whole object.'],
  [/Too many re-renders/i,
    'A React component keeps updating itself in a loop. Do not call setState directly while rendering; use an event or useEffect.'],
  [/Hydration failed|did not match\. Server:/i,
    'The page built on the server does not match what the browser drew. Avoid random values, dates or window checks during the first render.'],
  [/Element type is invalid/i,
    'A React component is imported wrongly (undefined). Check default vs named imports and the export.'],
  [/Each child in a list should have a unique "key"/i,
    'Add a unique key prop to each item rendered in a list.'],
  [/Minified React error #(\d+)/i,
    (m) => `React reported error #${m[1]}. Open the page in development mode for the full message.`],

  // ---- Backend messages (exact strings the backend raises) ----------------
  [/run \/analyze before|analyze the project before|no analysis found/i,
    'This project has not been analysed yet. Open the project and click Analyze first, then try again.'],
  [/run \/discover-failures before/i,
    'Weak spots have not been discovered yet. Run "Discover failures" for this project first, then generate experiments.'],
  [/no executable entrypoint detected|no entrypoint/i,
    'We could not find the file that starts this project. Make sure it has a main file such as app.py, main.py, server.js or index.js.'],
  [/experiment .* is (BLOCKED|RUNNING|DONE|FAILED|COMPLETED).*not READY/i,
    'This test is not ready to run. Re-analyze the project or pick a test that shows READY.'],
  [/blocked by sandbox security policy/i,
    'The safety sandbox blocked this test because it would break the safety rules. Pick a different test.'],
  [/OS-enforced network isolation is unavailable|refusing to start a network-capable sandbox/i,
    'Network isolation could not be turned on. Close the backend, start it again as Administrator (Windows Firewall rules are needed), and retry.'],
  [/sandbox execution is only allowed inside an isolated workspace/i,
    'Tests can only run on the isolated copy of your project. Re-import the project and try again.'],
  [/argv must be a non-empty list/i,
    'The run command was empty or invalid. Re-analyze the project and try again.'],
  [/refusing to destroy path outside workspace/i,
    'Cleanup was stopped because it pointed outside the project workspace. Nothing was deleted.'],
  [/CANCEL_REQUESTED|asked CD-SET to stop/i,
    'The test was stopped because you cancelled it.'],
  [/is not available in this environment/i,
    'The compiler or runtime needed for this project is not installed on this computer. Install it and restart the backend.'],
  [/required runtime\/compiler is not installed|not installed or not on PATH/i,
    'The tool needed to run this project (Java, Node, Python or Git) is not installed or not on PATH. Install it, restart the backend, and retry.'],
  [/no Java source files found/i,
    'No .java files were found in this project, so it cannot be run as Java.'],
  [/no chaos engine handler for fault_type/i,
    'This kind of test is not supported yet. Pick another test.'],
  [/dependencies are not installed|no node_modules folder|node_modules is not present/i,
    'The project packages are not installed. Run npm install in the project folder, then click Re-analyze.'],
  [/no readable package\.json/i,
    'No valid package.json was found, so tests cannot run. Add one to the project.'],
  [/no "test" script|still the npm-init placeholder/i,
    'package.json has no real test command. Add a "test" script (for example "jest" or "node --test") and try again.'],
  [/No test adapter is configured/i,
    'Automatic tests are not supported for this kind of project yet.'],
  [/Cloud IDE cannot execute files of type/i,
    'The Cloud IDE cannot run this kind of file yet. Open a .py, .js or .java file instead.'],
  [/binary files are not editable|file too large for Cloud IDE/i,
    'This file cannot be opened in the editor because it is binary or too large.'],
  [/internal harness files cannot be edited/i,
    'This is an internal Chaos Tutor file and cannot be edited.'],
  [/file path escapes project workspace|invalid file path|git metadata is not accessible|path is a directory/i,
    'That file path is not allowed. Pick a normal file inside the project.'],
  [/selected file not found|file not found|ENOENT|no such file or directory/i,
    'That file could not be found. It may have been moved or deleted. Refresh the file list and try again.'],
  [/program input is limited to 64 KB|stdin must be a string/i,
    'The program input is too big or is not plain text (limit 64 KB).'],
  [/no diagnosis found for this run|no tutor session (found )?for this run|tutor session not found/i,
    'The tutor explanation for this run is not ready yet. Open the run again in a moment, or run the test again.'],
  [/question is required|question must be text|answer must be text|content must be text|name must be text/i,
    'That field was empty or not plain text. Fill it in and try again.'],
  [/JSON body must be an object|invalid JSON body|empty request body/i,
    'The request was empty or malformed. Reload the page and try again.'],
  [/you do not have access to this project/i,
    'This project belongs to another account, so you cannot open it.'],
  [/Firebase authentication (required|is not configured)|authentication required|Firebase token has no user identity/i,
    'Sign-in is required or not set up on the backend. Sign in again, or check the Firebase settings in backend/.env.'],
  [/invalid or expired Firebase ID token/i,
    'Your sign-in expired. Sign out, sign in again and retry.'],
  [/API key is too long|custom verification endpoint must use HTTPS/i,
    'The API key or endpoint is not valid. Check it in Settings (endpoints must start with https://).'],
  [/no LLM API keys configured/i,
    'No AI key is set up, so the AI tutor is using built-in explanations. Add a key in Settings to get AI answers.'],
  [/all \d+ configured key\(s\) failed|AllProvidersFailed/i,
    'Every configured AI key failed (invalid, out of quota or offline). Check your keys in Settings and retry.'],
  [/rate.?limit|quota exceeded|\b429\b|resource exhausted/i,
    'The AI service is rate-limited or out of quota. Wait a minute and try again, or add another key in Settings.'],
  [/LLM tutor response missing|provider did not return a JSON object/i,
    'The AI gave an answer in the wrong format. Try again; the built-in explanation is used meanwhile.'],

  // ---- Git (exact backend messages) ---------------------------------------
  [/only public https:\/\/ repository URLs/i,
    'Only public https:// repository links are supported (not ssh://, git:// or http://).'],
  [/embedded credentials/i,
    'Do not put a username or password in the link. Import a public repository, or download the ZIP and upload it.'],
  [/repository URL (is required|must|contains invalid|is longer)|invalid repository URL|url is required|repository URL must be text/i,
    'That repository link is not valid. Use a link like https://github.com/owner/repo.'],
  [/invalid branch name|branch must be text|cannot determine which branch/i,
    'The branch name is not valid. Leave it empty to use the default branch.'],
  [/clone timed out|git timed out/i,
    'Git took too long. The repository may be very large or the internet is slow. Try again or upload a ZIP.'],
  [/destination already exists/i,
    'A folder for this import already exists. Try importing again.'],
  [/file too large in (repository|archive)/i,
    'A single file in this project is too big. Remove big data or build files and import again.'],
  [/filename exceeds|path exceeds/i,
    'A file or folder name inside the project is too long. Shorten it and import again.'],
  [/rejected (absolute|drive-qualified)/i,
    'This ZIP contains files with absolute paths (like C:\\ or /). Re-create the ZIP from inside the project folder.'],
  [/rejected symlink/i,
    'This project contains shortcuts (symbolic links), which are not allowed. Remove them and import again.'],
  [/more than \d+ source files|contains more than/i,
    'This project has too many files. Remove node_modules, build output and other generated folders, then import again.'],
  [/archive too large/i,
    'This ZIP is too large. Remove node_modules, build folders and large data files, then ZIP again.'],
  [/no git metadata to refresh|only git-imported projects/i,
    'Only projects imported from Git can be refreshed from Git.'],
  [/local changes|working tree.*(dirty|not clean)/i,
    'You edited files in the IDE. Refreshing from Git would overwrite them. Choose whether to keep or discard your changes.'],
  [/could not resolve host|unable to access|\bSSL\b|certificate verify/i,
    'Cannot reach the Git server. Check your internet connection and the repository link.'],

  // ---- Import / ZIP ------------------------------------------------------
  [/WinError 206|filename or extension is too long|path.*too long/i,
    'The project folder path is too long for Windows. Move the ChaosTutor folder to a short location such as C:\\chaos (for example C:\\chaos\\backend), restart the backend, and import again.'],
  [/WinError 5\b|permission denied|access is denied|EACCES|EPERM/i,
    'Windows blocked access to a file or folder. Close any program that is using the project (editor, terminal, antivirus scan) and try again.'],
  [/WinError 32|being used by another process/i,
    'A file is being used by another program. Close it (editor, terminal, File Explorer) and try again.'],
  [/No space left on device|disk full|not enough space/i,
    'Your disk is full. Free some space and try again.'],
  [/archive bomb|suspicious compression ratio/i,
    'This ZIP was rejected for safety because it expands to an unusually large size. Please upload a normal project ZIP without huge generated files.'],
  [/extracted size exceeds|exceeds .*byte limit|too large|payload too large/i,
    'This project is too large to import. Delete node_modules, build folders and large data files, ZIP it again, and retry (limit: 500 MB ZIP / 2 GB extracted).'],
  [/too many (files|entries)|entry count|50,?000/i,
    'This ZIP contains too many files. Remove node_modules, build output and other generated folders, then ZIP it again.'],
  [/outside destination|path traversal|\.\.[\\/]/i,
    'This ZIP contains files with unsafe paths, so it was rejected for your protection. Re-create the ZIP from the project folder itself.'],
  [/symlink|symbolic link/i,
    'This ZIP contains shortcuts (symbolic links), which are not allowed. Re-create the ZIP without them.'],
  [/BadZipFile|not a zip|is not a zip file|corrupt|CRC|End-of-central-directory/i,
    'This file is not a valid ZIP (or it is damaged). Create the ZIP again and upload it.'],
  [/encrypted|password required|Bad password/i,
    'This ZIP is password-protected. Upload a ZIP without a password.'],
  [/could not extract archive/i,
    'The ZIP could not be unpacked. Make sure it is a normal, complete ZIP file and try again.'],

  // ---- Git ---------------------------------------------------------------
  [/repository not found|not found or you do not have access|\bremote: not found/i,
    'That Git repository was not found. Check the URL, and make sure the repository is public.'],
  [/authentication failed|could not read username|terminal prompts disabled/i,
    'This repository needs a login. Only public repositories can be imported.'],
  [/git.*(not found|not installed|is not recognized)|git_available/i,
    'Git is not installed on this computer. Install Git for Windows, restart the backend, or import a ZIP instead.'],

  // ---- Backend / network -------------------------------------------------
  [/failed to fetch|networkerror|load failed|ECONNREFUSED|connection refused|backend request timed out/i,
    'Cannot reach the ChaosTutor backend. Make sure the backend window (start_backend.bat) is running and shows no errors, then try again.'],
  [/unauthori[sz]ed|invalid token|token expired/i,
    'You are signed out or your session expired. Sign in again and retry.'],
  [/forbidden/i,
    'You do not have permission to do this.'],
  [/project not found|experiment not found|run not found/i,
    'That item no longer exists. It may have been deleted. Refresh the page or pick another project.'],
  [/internal server error/i,
    'Something went wrong inside the backend. Check the backend window for details and try again.'],

  // ---- Chaos experiments -------------------------------------------------
  [/No experiments (were )?generated/i,
    'No tests are available for this project yet. Open Import Project, re-run the analysis, or try another project.'],
  [/Chaos tests cannot run on this project yet/i, null], // already written for humans
  [/not applicable/i,
    'This test does not apply to this project because the matching weak spot was not found in its code.'],
  [/already running|another (run|experiment) (is )?(in progress|active)/i,
    'Another test is already running on this project. Wait for it to finish or stop it first.'],
  [/could not (find|detect) (an )?entry ?point|no entry ?point/i,
    'We could not find the file that starts this project. Check that it has a main file such as app.py, main.py, server.js or index.js.'],

  // ---- Browser / network --------------------------------------------------
  [/ERR_NETWORK|ERR_CONNECTION|NetworkError|net::/i,
    'A network problem stopped the request. Check your internet connection and that the backend is running.'],
  [/\bCORS\b|cross-origin/i,
    'The browser blocked the request to the backend. Open the app from the address shown in the start window and restart the backend.'],
  [/Unexpected token .* JSON|JSON\.parse|is not valid JSON/i,
    'The backend sent an unreadable reply. Make sure the backend is running the latest version, then try again.'],
  [/ECONNRESET|socket hang up|connection reset|broken pipe/i,
    'The connection was cut in the middle. Try again.'],
  [/bad gateway|service unavailable|gateway time-?out/i,
    'The backend is not responding. Make sure it is running, then try again.'],
  [/TARGET_UNREACHABLE/i,
    'The tested project never started listening, so nothing could be tested. Check that it starts correctly (dependencies installed, reads the PORT variable) and run again.'],

  // ---- Firebase sign-in (login / register pages) --------------------------
  [/auth\/invalid-credential|auth\/wrong-password|auth\/user-not-found|invalid-login-credentials/i,
    'Email or password is wrong. Check both and try again, or use Forgot password.'],
  [/auth\/email-already-in-use/i,
    'An account with this email already exists. Sign in instead.'],
  [/auth\/weak-password/i,
    'The password is too weak. Use at least 6 characters.'],
  [/auth\/invalid-email/i,
    'That email address is not valid.'],
  [/auth\/too-many-requests/i,
    'Too many attempts. Wait a few minutes and try again.'],
  [/auth\/network-request-failed/i,
    'No internet connection. Check your network and try again.'],
  [/auth\/popup-closed-by-user|auth\/cancelled-popup-request/i,
    'The sign-in window was closed before finishing. Try again.'],
  [/auth\/user-disabled/i,
    'This account has been disabled.'],
  [/auth\/requires-recent-login/i,
    'For safety please sign in again, then repeat this action.'],

  // ---- Runtime errors printed by tested projects --------------------------
  [/ZeroDivisionError/i,
    'The project divided by zero and crashed. Check the value used as the divisor.'],
  [/KeyError: (.+)/i,
    (m) => `The project looked for the key ${m[1]} that does not exist in its data, and crashed. Check that the key is present or use .get().`],
  [/IndexError|list index out of range/i,
    'The project read a list position that does not exist and crashed.'],
  [/TypeError: (.+)/i,
    (m) => `The project used a value of the wrong type and crashed (${m[1]}).`],
  [/AttributeError: (.+)/i,
    (m) => `The project used something that does not exist on an object (${m[1]}).`],
  [/NameError: name '([^']+)'/i,
    (m) => `The project uses "${m[1]}" but it was never defined.`],
  [/ImportError|cannot import name/i,
    'The project could not import something it needs. Check the import lines and installed packages.'],
  [/IndentationError/i,
    'The project has an indentation mistake, so it could not start. Fix the spacing in the Cloud IDE and run again.'],
  [/JSONDecodeError/i,
    'The project tried to read invalid JSON data. Check the JSON file or request body.'],
  [/ReferenceError: (\w+) is not defined/i,
    (m) => `The project uses "${m[1]}" but it was never defined.`],
  [/Cannot read propert(y|ies) of (undefined|null)/i,
    'The project tried to use a value that is empty (undefined or null) and crashed. Check that the value exists first.'],
  [/UnhandledPromiseRejection|unhandled promise rejection/i,
    'The project has an async error that nothing catches (missing try/catch or .catch).'],
  [/JavaScript heap out of memory|MemoryError|OutOfMemoryError/i,
    'The project ran out of memory and was stopped. Check for endless loops or huge data.'],
  [/RecursionError|Maximum call stack|StackOverflowError/i,
    'The project called itself endlessly and crashed (infinite recursion).'],
  [/sqlite3?\.OperationalError|database is locked|no such table/i,
    'The project database is locked or missing a table. Check that the database file is set up.'],
  [/ConnectionRefusedError|connect ECONNREFUSED/i,
    'The project tried to connect to a service (database or another server) that is not running.'],

  // ---- Errors printed by the tested project itself -----------------------
  [/Cannot find module '([^']+)'/i,
    (m) => `The project needs the package "${m[1]}" but it is not installed. Add it to the project's dependency list (package.json) and import again.`],
  [/ModuleNotFoundError: No module named '([^']+)'/i,
    (m) => `The project needs the Python package "${m[1]}" but it is not installed. Add it to requirements.txt and import again.`],
  [/EADDRINUSE|address already in use|Only one usage of each socket address/i,
    'The project could not start because its port is already in use. Stop the other program using that port and try again.'],
  [/SyntaxError/i,
    'The project has a code syntax mistake, so it could not start. Fix the code in the Cloud IDE and run the test again.'],
  [/timed? ?out|ETIMEDOUT|deadline exceeded/i,
    'The action took too long and was stopped. Try again, or check that the project starts correctly.'],
];

function rawText(err) {
  if (err == null) return '';
  if (typeof err === 'string') return err;
  return String(err.message || err.error || err.detail || '');
}

// Pull the useful last line out of a Python traceback / Node stack, if present.
function lastErrorLine(raw) {
  const lines = raw.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (/^[\w.]*(Error|Exception|Warning)\b|^\w+Error:|^Error:/.test(lines[i])) return lines[i];
  }
  return lines.length > 1 ? lines[lines.length - 1] : raw;
}

// Does the text look technical (code, stack, error class, hex, etc.)?
function looksTechnical(raw) {
  return /Traceback \(most recent|^\s*at .+\(.+:\d+|\b[A-Z]\w*(Error|Exception)\b|\bE[A-Z]{3,}\b|0x[0-9a-f]+|errno|exit code|status code|\bHTTP \d{3}\b|\/[\w.-]+\/[\w.-]+|[A-Za-z]:\\|_v0|\{.*\}|\bNone\b|\bnull\b|undefined/i.test(raw);
}

export function friendlyErrorParts(err) {
  // Drop technical prefixes the backend adds ("upload rejected: ...")
  const raw = rawText(err).replace(/^\s*upload rejected:\s*/i, '').trim();
  if (!raw) return { message: 'Something went wrong. Please try again.', detail: '', recognised: false };

  for (const [pattern, reply] of RULES) {
    const m = raw.match(pattern);
    if (!m) continue;
    if (reply === null) return { message: raw, detail: '', recognised: true };
    const message = typeof reply === 'function' ? reply(m) : reply;
    return { message, detail: raw, recognised: true };
  }

  // Not a known error. Never show a raw technical line as-is: wrap it in a plain sentence
  // and keep the original text (shortened) so nothing is hidden.
  if (looksTechnical(raw)) {
    const core = lastErrorLine(raw).slice(0, 200);
    return {
      message: `Something unexpected went wrong. Try again; if it keeps happening, check the backend window. (Technical detail: ${core})`,
      detail: raw,
      recognised: false,
    };
  }
  // Plain human-readable sentence from the backend: already understandable, keep it exactly.
  return { message: raw, detail: '', recognised: false };
}

export function friendlyError(err) {
  return friendlyErrorParts(err).message;
}

// For one line of an event/terminal log: only rewrite lines that match a KNOWN error rule,
// so ordinary progress lines are never replaced by the generic fallback.
export function friendlyLogLine(text) {
  const raw = String(text || '');
  const parts = friendlyErrorParts(raw);
  return parts.recognised && parts.detail ? parts.message : raw;
}
