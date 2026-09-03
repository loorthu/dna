#!/bin/sh
# Run the nginx WORKER as an identity the recordings share accepts.
#
# On a network share, access is decided by the identity the client sends, not by the mode bits a
# local `ls` shows. Archives are 0644 inside 0755 directories owned by the collector's uid, and
# the stock `nginx` user (uid 101) is refused the open() anyway: the server does not know that
# uid, and — this is the part that wastes an afternoon — it discounts the SUPPLEMENTARY group
# list the client sends, deriving groups from the uid at its own end instead. So adding a group
# to the nginx user, or to the container via `group_add`, changes nothing the server will honour.
#
# What works is the PRIMARY identity. Proven on the real share: uid 101 with group 20 alongside
# is denied, while both 2443:20 and 65534:20 read the same file, the difference being that in
# those two gid 20 is primary.
#
# So a user is created here with the collector's own uid and gid, and nginx is pointed at it —
# the same identity that wrote the files now serves them. nginx wants a NAME in `user`, not a
# number, which is why the account is made rather than the directive being given digits.
#
# Unset does nothing, which is right for a deployment serving off a local disk, where the mode
# bits settle it and the stock user is fine.
set -e

uid="${NGINX_UID:-}"
gid="${NGINX_SHARE_GID:-}"
[ -z "$uid" ] && [ -z "$gid" ] && exit 0

conf=/etc/nginx/nginx.conf

# Reuse the group that already holds this gid — on Alpine, 20 is `dialout` — rather than failing
# on a duplicate.
group="$(getent group "$gid" 2>/dev/null | cut -d: -f1)"
if [ -z "$group" ] && [ -n "$gid" ]; then
    group="dnashare"
    addgroup -g "$gid" "$group"
fi

if [ -n "$uid" ]; then
    user="$(getent passwd "$uid" 2>/dev/null | cut -d: -f1)"
    if [ -z "$user" ]; then
        user="dnaserve"
        adduser -D -H -u "$uid" ${group:+-G "$group"} "$user"
    fi
    # The worker still needs somewhere to spill request bodies and proxied responses; those
    # directories are shipped owned by `nginx`, who is no longer the one writing them.
    chown -R "$uid:${gid:-$uid}" /var/cache/nginx
    sed -i "s/^user .*/user $user${group:+ $group};/" "$conf"
    echo "$0: nginx workers will run as $user ($uid:${gid:-$uid}) to read the recordings share"
elif [ -n "$group" ]; then
    # Group only. Weaker — a server that discounts supplementary groups will ignore it — but it
    # is what a local-disk deployment needs and costs nothing to keep.
    addgroup nginx "$group"
    echo "$0: nginx joined group $group ($gid)"
fi
