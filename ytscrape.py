import requests
import requests_random_user_agent
import json
import hashlib
import time
from urllib.parse import unquote

# set "cookie" to your cookie
# to find it, navigate to 'youtube.com/feed/history' and grab the full cookie line
# it should look something like this:
# cookie = "YSC=XXX; VISITOR_INFO1_LIVE=xxx; SID=xxx.; __Secure-
cookie = "YSC=xxx; VISITOR_INFO1_LIVE=xxx; SID=xxx.; __Secure-3PSID=xxx-xxx-xxx.; HSID=xxx-xxx; SSID=xxx; APISID=xxx/xxx; SAPISID=xxx-xxx/xxx; __Secure-3PAPISID=xxx-xxx/xxx; SIDCC=xxx-xxx-xxx; __Secure-3PSIDCC=xxx-xxx"

cookiedat = cookie.split("; ")

s = requests.Session()
for x in cookiedat:
    parts = x.split("=")
    (key, value) = (parts[0], parts[1])
    s.cookies.set(key, value)

data = s.get("https://www.youtube.com/feed/history", headers={"Cookie": cookie}).text

# parse out some other useful form parameters
ytcfg = json.loads(data.split("ytcfg.set(")[2].split(");")[0])

# grab session token
sessiontoken = ytcfg["XSRF_TOKEN"]

data = data.split("var ytInitialData = ")[1]

# cheese json loader to find end of dictionary
try:
    json.loads(data)
    # this should always fail
    raise Exception
except Exception as e:
    column = int(str(e).split(" column ")[1].split(" ")[0])

data = json.loads(data[:column-1])

videos = []

# sanity check ourselves here
assert len(data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]) == 1

continuation = None

groupings = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"]

def parse_groupings(groupings):

    continuation = None
    ret = []

    for group in groupings:

        groupvids = []

        # check for the continuation
        if "continuationItemRenderer" in group:
           continuation = group
           break

        if "simpleText" in group["itemSectionRenderer"]["header"]["itemSectionHeaderRenderer"]["title"]:
            groupdate = group["itemSectionRenderer"]["header"]["itemSectionHeaderRenderer"]["title"]["simpleText"]
        else:
            assert len(group["itemSectionRenderer"]["header"]["itemSectionHeaderRenderer"]["title"]["runs"]) == 1
            groupdate = group["itemSectionRenderer"]["header"]["itemSectionHeaderRenderer"]["title"]["runs"][0]["text"]

        print(groupdate)

        vids = group["itemSectionRenderer"]["contents"]
        count = -1
        for vid in vids:
            count += 1
            # title, id/url, channel, length, description, thumbnail, viewcount

            video = {}

            # title
            assert len(vid["videoRenderer"]["title"]["runs"]) == 1
            video["title"] = vid["videoRenderer"]["title"]["runs"][0]["text"]

            # video ID
            video["id"] = vid["videoRenderer"]["videoId"]

            # channel
            if "ownerText" in vid["videoRenderer"]:
                assert len(vid["videoRenderer"]["ownerText"]["runs"]) == 1
                video["channel"] = {
                    "name": vid["videoRenderer"]["ownerText"]["runs"][0]["text"],
                    "url": vid["videoRenderer"]["ownerText"]["runs"][0]["navigationEndpoint"]["browseEndpoint"]["canonicalBaseUrl"],
                }
            else:
                video["channel"] = {
                    "name": "(none)",
                    "fulldata": vid["videoRenderer"]["title"]["accessibility"]["accessibilityData"]["label"],
                    "url": "/watch?v=%s" % vid["videoRenderer"]["videoId"],
                }
                

            # length
            if "lengthText" in vid["videoRenderer"]:
                video["length"] = vid["videoRenderer"]["lengthText"]["simpleText"]
            else:
                video["length"] = "(live)"

            # description (short description byline)
            if "descriptionSnippet" in vid["videoRenderer"]:
                assert len(vid["videoRenderer"]["descriptionSnippet"]["runs"]) == 1
                video["description"] = vid["videoRenderer"]["descriptionSnippet"]["runs"][0]["text"]
            else:
                # for videos without a description, theres no descriptionSnippet
                pass

            # thumbnail (just save the whole dict here)
            video["thumbnail"] = vid["videoRenderer"]["thumbnail"]

            # viewcount
            if "viewCountText" in vid["videoRenderer"]:
                if "simpleText" in vid["videoRenderer"]["viewCountText"]:
                    video["viewcount"] = vid["videoRenderer"]["viewCountText"]["simpleText"]
                else:
                    video["viewcount"] = "(live)"
            else:
                video["viewcount"] = "(unknown)"

            groupvids.append(video)

        ret.append({"date": groupdate, "videos": groupvids})

    return (ret, continuation)

(outvids, continuation) = parse_groupings(groupings)
videos.extend(outvids)

# we've now parsed the original page and can now do continuations
count = 0
while continuation:
    print(continuation)
    ctoken = unquote(continuation["continuationItemRenderer"]["continuationEndpoint"]["continuationCommand"]["token"])

    apikey = ytcfg["INNERTUBE_API_KEY"]
    target = "https://www.youtube.com/youtubei/v1/browse?key=%s" % apikey

    headers = {
        "Authorization": "SAPISIDHASH " + str(int(time.time())) + "_" + hashlib.sha1(' '.join([str(int(time.time())), s.cookies.get("SAPISID"), 'https://www.youtube.com']).encode()).hexdigest(),
        "DNT": "1",
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/feed/history",
        "X-Goog-Authuser": "0",
        "X-Goog-Visitor-Id": unquote(ytcfg["VISITOR_DATA"]),
        "X-Origin": "https://www.youtube.com",
        "X-Youtube-Client-Name": "1",
        "X-Youtube-Client-Version": ytcfg["INNERTUBE_CLIENT_VERSION"],
    }

    # update our clickTrackingParam
    ytcfg["INNERTUBE_CONTEXT"]["clickTracking"]["clickTrackingParams"] = continuation["continuationItemRenderer"]["continuationEndpoint"]["clickTrackingParams"]

    # insert some missing data
    ytcfg["INNERTUBE_CONTEXT"]["user"]["onBehalfOfUser"] = ytcfg["DELEGATED_SESSION_ID"]

    payload = {
        "context": ytcfg["INNERTUBE_CONTEXT"],
        "continuation": ctoken,
    }

    result = s.post(target, headers=headers, json=payload)
    data = result.json()
    errcnt = 0
    while "error" in data:
        print("got error, retrying")
        result = s.post(target, headers=headers, json=payload)
        data = result.json()
        errcnt += 1
        if errcnt == 10:
            raise Exception
        time.sleep(1)
    with open("out.bin", "wb") as f:
        f.write(result.text.encode("utf-8"))

    # some sanity checking
    assert len(data["onResponseReceivedActions"]) == 1

    (outvids, continuation) = parse_groupings(data["onResponseReceivedActions"][0]["appendContinuationItemsAction"]["continuationItems"])
    videos.extend(outvids)
    count += 1

# save the data to disk
with open("output.txt", "wb") as f:
    f.write(json.dumps(videos).encode("utf-8"))
