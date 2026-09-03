#!/bin/sh
# Put the nginx WORKER user in the group that owns the recordings share.
#
# WHY THIS CANNOT BE `group_add` ALONE. nginx drops privileges in each worker with
# initgroups(user, group) before setuid(), and initgroups REPLACES the supplementary group list
# with whatever /etc/group says that user belongs to. A group handed to the container's init
# process is therefore discarded the moment a worker starts — the container has the group, and
# the process serving the files does not.
#
# WHY A GROUP AT ALL. On a network share the server decides access by identity, not by the mode
# bits: archives are 0644 inside 0755 directories and the stock `nginx` uid is refused anyway,
# because it is a uid the server has never heard of. Membership of the owning group is what gets
# it in — the same group the collector writes as, which is why the compose file passes
# COLLECTOR_GID here rather than a second number that could drift from it.
#
# Unset does nothing, which is right for a deployment serving off a local disk.
set -e

gid="${NGINX_SHARE_GID:-}"
[ -z "$gid" ] && exit 0

name="$(getent group "$gid" | cut -d: -f1)"
if [ -z "$name" ]; then
    name="share"
    addgroup -g "$gid" "$name"
fi

addgroup nginx "$name"
echo "$0: nginx joined group $name ($gid) to read the recordings share"
