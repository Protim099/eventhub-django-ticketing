"""EventHub project package.

If `mysqlclient` is not installed (common on Windows without build tools) we fall
back to PyMySQL, which is a pure-python drop-in replacement.
"""
try:
    import MySQLdb  # noqa: F401
except ImportError:  # pragma: no cover
    try:
        import pymysql

        pymysql.version_info = (2, 2, 1, "final", 0)
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass
