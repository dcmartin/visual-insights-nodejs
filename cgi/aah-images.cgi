#!/bin/tcsh -b
setenv APP "aah"
setenv API "images"

# debug on/off
setenv DEBUG true
setenv VERBOSE true

# environment
if ($?LAN == 0) setenv LAN "192.168.1"
if ($?DIGITS == 0) setenv DIGITS "$LAN".30
if ($?TMP == 0) setenv TMP "/var/lib/age-at-home"
if ($?CREDENTIALS == 0) setenv CREDENTIALS /usr/local/etc
if ($?LOGTO == 0) setenv LOGTO /dev/stderr

###
### dateutils REQUIRED
###

if ( -e /usr/bin/dateutils.dconv ) then
   set dateconv = /usr/bin/dateutils.dconv
else if ( -e /usr/local/bin/dateconv ) then
   set dateconv = /usr/local/bin/dateconv
else
  echo "No date converter; install dateutils" >& /dev/stderr
  exit 1
endif

# don't update statistics more than once per (in seconds)
setenv TTL 300
setenv SECONDS `date "+%s"`
setenv DATE `echo $SECONDS \/ $TTL \* $TTL | bc`

# default image limit
if ($?IMAGE_LIMIT == 0) setenv IMAGE_LIMIT 10000
if ($?IMAGE_SET_LIMIT == 0) setenv IMAGE_SET_LIMIT 100

if ($?QUERY_STRING) then
    set db = `echo "$QUERY_STRING" | sed 's/.*db=\([^&]*\).*/\1/'`
    if ($db == "$QUERY_STRING") unset db
    set class = `echo "$QUERY_STRING" | sed 's/.*class=\([^&]*\).*/\1/'`
    if ($class == "$QUERY_STRING") unset class
    set id = `echo "$QUERY_STRING" | sed 's/.*id=\([^&]*\).*/\1/'`
    if ($id == "$QUERY_STRING") unset id
    set ext = `echo "$QUERY_STRING" | sed 's/.*ext=\([^&]*\).*/\1/'`
    if ($ext == "$QUERY_STRING") unset ext
    set since = `echo "$QUERY_STRING" | sed 's/.*since=\([^&]*\).*/\1/'`
    if ($since == "$QUERY_STRING") unset since
    set limit = `echo "$QUERY_STRING" | sed 's/.*limit=\([^&]*\).*/\1/'`
    if ($limit == "$QUERY_STRING") unset limit
    set force = `echo "$QUERY_STRING" | sed 's/.*force=\([^&]*\).*/\1/'`
    if ($force == "$QUERY_STRING") unset force
endif

if ($?db == 0 && $?id) unset id
if ($?since && $?id) unset id
if ($?db == 0) set db = all

if ($?limit && $db == "all") then
  unset limit
else if ($?limit) then
  if ($limit > $IMAGE_LIMIT) set limit = $IMAGE_LIMIT
endif

if ($?DEBUG) echo `date` "$0 $$ -- START ($QUERY_STRING)" >>! $LOGTO

##
## ACCESS CLOUDANT
##
if ($?CLOUDANT_URL) then
  set CU = $CLOUDANT_URL
else if (-s $CREDENTIALS/.cloudant_url) then
  set cc = ( `cat $CREDENTIALS/.cloudant_url` )
  if ($#cc > 0) set CU = $cc[1]
  if ($#cc > 1) set CN = $cc[2]
  if ($#cc > 2) set CP = $cc[3]
  if ($?CP && $?CN && $?CU) then
    set CU = 'https://'"$CN"':'"$CP"'@'"$CU"
  else if ($?CU) then
    set CU = "https://$CU"
  endif
else
  echo `date` "$0:t $$ -- FAILURE: no Cloudant credentials" >>& $LOGTO
  goto done
endif

# find updates
set url = "$HTTP_HOST/CGI/aah-updates.cgi"
set updates = ( `curl -s -q -f -L "$url" | jq '.'` )
if ($#updates == 0) then
  if ($?VERBOSE) echo `date` "$0 $$ ++ FAILURE ($url)" >>&! $LOGTO
  set output = '{"error":"NO UPDATES -- '"$url"'"}'
  goto output
endif

# get last check time (seconds since epoch)
set last_update_check = ( `echo "$updates" | jq -r '.date'`)

# find devices
if ($db == "all") then
  set url = "$HTTP_HOST/CGI/aah-devices.cgi"
  set devices = ( `curl -s -q -L "$url" | jq -r '.devices[].name'` )
  if ($#devices == 0) then
    if ($?VERBOSE) echo `date` "$0 $$ ++ FAILURE ($url)" >>&! $LOGTO
    goto done
  endif
else
  set devices = ($db)
endif

if ($#devices == 0) then
  if ($?VERBOSE) echo `date` "$0 $$ ++ FAILURE ($url)" >>&! $LOGTO
  set output = '{"error":"NO DEVICES"}'
  goto output
endif

if ($?DEBUG) echo `date` "$0 $$ ++ SUCCESS -- devices ($devices) -- last check: $last_update_check" >>&! $LOGTO

# check all devices
foreach d ( $devices )
  # indicate success
  if ($db == "$d") then
    set last_update_check = ( `echo "$updates" | jq -r '.devices[]|select(.name=="'"$d"'").date'`)
    if ($#last_update_check == 0) set last_update_check = $DATE
    set last_image_check = ( `curl -s -q -f -L "$CU/$db-images/_all_docs?include_docs=true&descending=true&limit=1" | jq -r '.rows[].doc.date'` )
    if ($#last_image_check == 0) set last_image_check = 0
    @ delay = $last_update_check - $last_image_check
    if ($delay > $TTL) then
      # initiate new output
      set qs = "$QUERY_STRING"
      setenv QUERY_STRING "device=$d"
      if ($?force) then
        setenv QUERY_STRING "$QUERY_STRING&force=true"
      endif
      if ($?DEBUG) echo `date` "$0 $$ ++ DELAY ($delay) -- REQUESTING ./$APP-make-$API.bash ($QUERY_STRING)" >>! $LOGTO
      ./$APP-make-$API.bash
      setenv QUERY_STRING "$qs"
    endif
    set found = "$d"
    break
  endif
end

if ($db != "all") then
  if  ($?found == 0) then
    set output = '{"error":"not found","db":"'"$db"'"}'
    goto output
  endif
  set devices = ( $db )
endif

# test if singleton requested
if ($db != "all" && ( $?id || $?limit )) then
  if ($?id) then
    set singleton = true
  else if ($?limit) then
    if ($limit == 1) set singleton = true
  else
    # not a singleton request
    unset singleton
  endif
endif

# define OUTPUT
set OUTPUT = "$TMP/$APP-$API-$QUERY_STRING.$DATE.json"

if ($?singleton) then
  if ($?id) then
    set url = "$db-images/$id"
  else
    set url = "$db-images/_all_docs?include_docs=true&descending=true&limit=$IMAGE_LIMIT"
  endif
  set out = "/tmp/$0:t.$$.json"
  curl -s -q -f -L "$CU/$url" -o "$out"
  if ($status == 22 || $status == 28 || ! -s "$out") then
    if ($?id) then
      set output = '{"error":"not found","db":"'"$db"'","id":"'"$id"'"}'
      goto output
    else if ($?limit)
      set output = '{"error":"not found","db":"'"$db"'","limit":"'"$limit"'"}'
      goto output
    else
      set output = '{"error":"not found","db":"'"$db"'"}'
      goto output
    endif
  endif
  if ($?limit) then
    set json = ( `jq '.rows[].doc' "$out"` )
  else
    set json = ( `jq '.' "$out"` )
  endif
  # clean-up
  /bin/rm -f "$out"

  # ensure id is specified
  set id = ( `echo "$json" | jq -r '._id'` )
  set crop = ( `echo "$json" | jq -r '.crop'` )
  set class = ( `curl -s -q -f -L "$HTTP_HOST/CGI/aah-updates.cgi?db=$db&id=$id" | jq -r '.class?' | sed 's/ /_/g'` )

  # test if non-image (i.e. json) requested
  if ($?ext == 0) then
    echo "$json" | jq '{"id":._id,"class":"'"$class"'","date":.date,"type":.type,"size":.size,"crop":.crop,"depth":.depth,"color":.color}'  >! "$OUTPUT"
    goto output
  endif

  # handle singleton (image)
  if ($#class == 0 || $class == "null") then
      set output = '{"error":"no class","db":"'"$db"'","id":"'"$id"'"}'
      goto output
  endif

  # find original
  if ($ext == "full") set path = "$TMP/$db/$class/$id.jpg"
  if ($ext == "crop") set path = "$TMP/$db/$class/$id.jpeg"
  if (-s "$path") then
    if ($?DEBUG) echo `date` "$0 $$ -- SINGLETON ($path)" >>! $LOGTO
    echo "Last-Modified:" `$dateconv -i '%s' -f '%a, %d %b %Y %H:%M:%S %Z' $DATE`
    echo "Access-Control-Allow-Origin: *"
    echo "Content-Location: $HTTP_HOST/CGI/$APP-$API.cgi?db=$db&id=$id&ext=$ext"
    echo "Content-Type: image/jpeg"
    echo ""
    ./aah-images-label.csh "$path" "$class" "$crop"
    goto done
  endif
  set output = '{"error":"not found","db":"'"$db"'","id":"'"$id"'"}'
  goto output
endif

#
# NOT A SINGLETON
#

#
# PROCESS REQUESTED DEVICES
#

@ k = 0
set all = '{"date":'"$DATE"',"devices":['
# handle all (json)
foreach d ( $devices )
  set lud = ( `echo "$updates" | jq -r '.devices?[]|select(.name=="'"$d"'")|.date'` )

  if ($?DEBUG) echo `date` "$0 $$ ++ UPDATES ($d) -- last check: $lud" >>&! $LOGTO

  # get most recent image available
  set url = "$CU/$d-images/_all_docs?include_docs=true&limit=1&descending=true"
  set out = "/tmp/$0:t.$$.json"
  curl -s -q -f -L "$url" -o "$out"
  if ($status != 22 && -s "$out") then
    set lid = ( `jq '.rows[].doc.date' "$out"` )
    set total_rows = ( `jq '.total_rows' "$out"` )
    if ($#lid == 0 || $lid == "null")  set lid = 0
    if ($#total_rows == 0 || $total_rows == "null")  set total_rows = 0
  else
    if ($?DEBUG) echo `date` "$0 $$ ++ NO UPDATES ($d)" >>&! $LOGTO
    /bin/rm -f "$out"
    continue
  endif
  /bin/rm -f "$out"



  ####
  #### LOOK AT THIS LATER -- NUMBERS ARE ARBITRARY
  ####

  if ($?since) then
    @ delay = $lud - $since
  else
    @ delay = $lud - $lid
  endif

  if ($?limit == 0) then
    @ estimate = $delay / 5
  else
    @ estimate = $limit
  endif
  if ($estimate > $IMAGE_LIMIT) then
    set estimate = $IMAGE_LIMIT
  else if ($estimate == 0) then
    @ estimate = 5
  endif

  if ($?DEBUG) then
    set LUD = `$dateconv -i %s "$lud"` 
    set LID = `$dateconv -i %s "$lid"` 
    echo `date` "$0 $$ ++ DEVICE ($d) -- TOTAL ($total_rows) d) delay ($delay) -- estimate ($estimate) -- image: $LID -- update: $LUD" >>&! $LOGTO
  endif

  # process this db
  if ($db != "all" && $d == "$db") then
    # get recent rows
    set url = "$CU/$d-images/_all_docs?include_docs=true&&descending=true&limit=$estimate"
    set out = "/tmp/$0:t.$$.json"
    @ try = 0
    @ rtt = 5
    while ($try < 3)
      curl -m "$rtt" -s -q -f  -L "$url" -o "$out"
      if ($status == 22 || $status == 28 || ! -s "$out") then
	/bin/rm -f "$out"
	@ try++
	@ rtt += $rtt
	continue
      endif
      break
    end
    if (! -s "$out") then
      /bin/rm -f "$out"
      set output = '{"error":"failure","db":"'"$d-images"'}'
      goto output
    endif
    # select subset based on limit specified and date
    if ($?since == 0 && $?limit) then
      set ids = ( `jq '[limit('"$limit"';.rows?|sort_by(.id)|reverse[].doc|select(.date<='"$lid"')._id)]' "$out"` )
      set len = ( `echo "$ids" | jq '.|length'` )
      if ($?DEBUG)  echo `date` "$0:t $$ -- found $len ids" `echo "$ids" | jq -c '.'` >& $LOGTO
      echo '{"name":"'"$d"'","date":'"$lid"',"count":'"$len"',"total":'"$total_rows"',"limit":'"$limit"',"ids":'"$ids"' }' >! "$OUTPUT"
    else if ($?since) then
      set all = ( `jq -r '[.rows[]?.doc|select(.date<='"$lid"')|select(.date>'"$since"')._id]' "$out"` )
    else 
      # the limit will be estimate iff limit was specified
      set all = ( `jq -r '.rows[]?.doc._id' "$out"` )
    endif
    set len = $#all
    if ($?limit) then
      if ($limit < $len) then
	set ids = ( $all[1-$limit] )
      endif
    else
      set limit = 0
    endif
    set ids = ( $all[1-$len] )
    set num = $#ids
    if ($num > 0) then
      set all = ( `echo "$ids" | sed 's/\([^ ]*\)/"\1"/g' | sed 's/ /,/g'` )
    else
      set all = ""
    endif
    echo '{"name":"'"$d"'","date":'"$lid"',"count":'"$num"',"total":'"$total_rows"',"limit":'"$limit"',"ids":['"$all"']}' >! "$OUTPUT"
    rm -f "$out"
    goto output
  else if ($db == "all") then
    set json = '{"name":"'"$d"'","date":'"$lid"',"total":'"$total_rows"'}'
  else
    unset json
  endif
  if ($k) set all = "$all"','
  @ k++
  if ($?json) then
    set all = "$all""$json"
  endif
end

set all = "$all"']}'
echo "$all" | jq -c '.' >! "$OUTPUT"

#
# output
#

output:

echo "Content-Type: application/json; charset=utf-8"
echo "Access-Control-Allow-Origin: *"

if ($?output == 0 && $?OUTPUT) then
  if (-s "$OUTPUT") then
    @ age = $SECONDS - $DATE
    echo "Age: $age"
    @ refresh = $TTL - $age
    if ($refresh < 0) @ refresh = $TTL
    echo "Refresh: $refresh"
    echo "Cache-Control: max-age=$TTL"
    echo "Last-Modified:" `$dateconv -i '%s' -f '%a, %d %b %Y %H:%M:%S %Z' $DATE`
    echo ""
    jq -c '.' "$OUTPUT"
    if ($?DEBUG) echo `date` "$0 $$ -- output ($OUTPUT) Age: $age Refresh: $refresh" >>! $LOGTO
    /bin/rm -f "$OUTPUT"
    goto done
  endif
endif

echo "Cache-Control: no-cache"
echo "Last-Modified:" `$dateconv -i '%s' -f '%a, %d %b %Y %H:%M:%S %Z' $DATE`
echo ""
if ($?output) then
   echo "$output"
else
   echo '{ "error": "not found" }'
endif

# done

done:

@ now = `date "+%s"`
@ elapsed = $now - $SECONDS

if ($?DEBUG) echo `date` "$0 $$ -- FINISH ($elapsed)" >>! $LOGTO
