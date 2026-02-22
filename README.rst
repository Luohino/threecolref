3ColRef — A Simple Reference Image Viewer
========================================

`3ColRef <https://github.com/Luohino/threecolref>`_ lets you quickly arrange your reference images and view them while you create. Its minimal interface is designed not to get in the way of your creative process.

|python-version| |downloads-total| |downloads-latest|

.. |python-version| image:: https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11-blue
   :target: https://www.python.org/

.. |downloads-total| image:: https://img.shields.io/github/downloads/Luohino/threecolref/total.svg
   :target: https://github.com/Luohino/threecolref/releases

.. |downloads-latest| image:: https://img.shields.io/github/downloads/Luohino/threecolref/latest/total.svg
   :target: https://github.com/Luohino/threecolref/releases


Installation
------------

Stable Release
~~~~~~~~~~~~~~

Get the file for your operating system (Windows, Linux, macOS) from the `latest release <https://github.com/Luohino/threecolref/releases>`_.

**Linux users** need to give the file executable rights before running it. Optional: If you want to have 3ColRef appear in the app menu, save the desktop file from the `release section <https://github.com/Luohino/threecolref/releases>`_ in ``~/.local/share/applications``, and adjust the path names in the desktop file to match the location of your 3ColRef installation.

Follow further releases via GitHub.


Development Version
~~~~~~~~~~~~~~~~~~~

To get the current development version, you need to have a working Python 3 environment. Run the following command to install the development version::

  pip install git+https://github.com/Luohino/threecolref.git

Then run ``threecolref``


Features
--------

* Move, scale, rotate, crop and flip images
* Mass-scale images to the same width, height or size
* Mass-arrange images vertically, horizontally or for optimal usage of space
* Add text notes
* Enable always-on-top-mode and disable the title bar:




Regarding the .3col file format
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All images are embedded into the .3col file as PNG or JPG. The file format is a sqlite database inside which the images are stored in an sqlar table—meaning they can be extracted with the `sqlite command line program <https://www.sqlite.org/cli.html>`_::

  sqlite3 myfile.3col -Axv


Notes for developers
--------------------

3ColRef is written in Python and PyQt6. For more info, see `CONTRIBUTING.rst <https://github.com/Luohino/threecolref/blob/main/CONTRIBUTING.rst>`_.
