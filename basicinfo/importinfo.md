this is imprtant info . always read this first . 

this  a folder that is using mutagen to synce all its files
with a vps ubutnu . any file change you do here will take place there . 

but any server code run that you might run in terminal will 
not work as this is just a local copy of all the files . 

fronentcodelocation : 
/home/s/aproject/nobanno3/frontend 
fornendt is only on local pc . request access if needed 

------------------------------------------------------------------------------
MUTAGEN SYNC NOTES (codes-sync)
------------------------------------------------------------------------------

- the mutagen sync session is called `codes-sync`.
  local (alpha)  : /home/s/aproject/aserver
  server (beta)  : s@200.234.36.38:~/codes   (ssh)

- check sync status locally with:
      mutagen sync list codes-sync

- the sync daemon may disconnect from the beta. if the server is missing
  a new/changed file, reconnect & force it to scan/reconcile:
      mutagen sync monitor codes-sync        # watch it re-scan + reconcile
  and confirm the beta shows "Connected: Yes".

- the sync is NOT instant. after editing files here, give it a few seconds
  (mutagen scans + reconciles), then verify the file exists on the server:
      ssh s@200.234.36.38 "ls -la ~/codes/nobobackend/..."

- mutagen only copies FILES. it does NOT run migrations. to apply a new
  migration (e.g. api/migrations/0014_*.py) you must ssh in and run:
      ssh s@200.234.36.38 "cd ~/codes/nobobackend && .venv/bin/python manage.py migrate"

- check for unresolved conflicts (both sides edited the same file):
      mutagen sync list codes-sync      # look for "Conflicts: N"
  resolve them, otherwise changes may not propagate as expected.

- never run server commands locally - this folder is only a synced copy. 



sometimes error happen when server is not propely synced with local folder . ensure sync then test 