import tempfile
import subprocess

import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def python(code:str):
    """Execute Python code.

    Args:
        code: Python source code to execute.

    Returns:
        A dict containing the process return code (int), standard output (str), and
        standard error (str).
    """

    with tempfile.NamedTemporaryFile('w', delete_on_close=False) as f:
        f.write(code)
        f.close()
        if log.isEnabledFor(logging.DEBUG):
            log.debug(f"Written code\n{code}\nto file {f.name}")
        python_command = ['python3', f.name]
        python_err = python_out = ''
        python_ret = -1
        proc = subprocess.Popen(
            python_command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8'
        )
        try:
            python_ret = proc.wait()        
        finally:
            python_err = ''.join(proc.stderr)
            python_out = ''.join(proc.stdout)
        ret = {
            'return_code': str(python_ret), 
            'stdout': python_out, 
            'stderr': python_err
        }
        log.debug(f"Returning\n{ret}")
        if python_ret != 0:
            return f"Python subprocess returned code {python_ret}.\n{python_err}"
        return python_out + python_err


OLLAMA_AGENTIC_TOOLS = {
    'python': python
}

