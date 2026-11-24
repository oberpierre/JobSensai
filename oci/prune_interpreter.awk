# Drops the parts of the hermetic CPython runtime an image never executes. The
# entrypoint runs bin/python3 directly, and that binary links CPython statically,
# so the other bin/ entries, libpython and the Tk/Tcl stack are dead weight.
$1 ~ /\.runfiles\/[^\/]*python_3_[0-9]+_x86_64-unknown-linux-gnu\// {
    split($1, halves, /python_3_[0-9]+_x86_64-unknown-linux-gnu\//)
    rel = halves[2]
    if (rel ~ /^bin\// && rel != "bin/python3") next
    if (rel ~ /^lib\/libpython/) next
    if (rel ~ /^lib\/(libtcl|libtk|tcl[0-9]|tk[0-9]|itcl|thread[0-9])/) next
    if (rel ~ /^lib\/python3\.[0-9]+\/(tkinter|idlelib|turtledemo|ensurepip|lib2to3)(\/|$)/) next
    if (rel ~ /^lib\/python3\.[0-9]+\/lib-dynload\/_tkinter\./) next
    if (rel ~ /^lib\/python3\.[0-9]+\/site-packages\/(pip|pip-[^\/]*)(\/|$)/) next
    if (rel ~ /^(include|share)\//) next
}
