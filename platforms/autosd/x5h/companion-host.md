# X5H companion host: always-on bench gateway for remote development

Stands up a small always-on PC next to the X5H that owns the bench LAN,
routes a tailnet into it, and serves the rescue paths (TFTP, NFS) and the
serial consoles. It is what makes the board reachable when nobody is in
the room, and it is where external developers' access is scoped.

> **Status: executed and verified on hardware, 2026-08-10.** The procedure
> below has been run end to end on a companion host, including the reboot
> drill, both netboot rescue paths, and the access-tier tests from a real
> external node. Markers recorded: `COMPANION_REBOOT_PASS`, `ACL_ADMIN_OK`,
> `RESCUE_NETBOOT_YOCTO_PASS`, `RESCUE_NETBOOT_AUTOSD_PASS`,
> `NEGATIVE_ACCESS_PASS`, `REMOTE_REHEARSAL_PASS`. Everything the first draft
> got wrong is corrected in place, and the reasons are kept alongside the
> commands so they do not have to be rediscovered.

## Why a separate machine

The board's bench dependencies used to live on a developer's workstation:
the TFTP server U-Boot pulled kernels from, the NFS export it mounted as
root, and the USB serial adapters. That workstation gets rebooted, taken
home, and put to sleep. [UFS self-boot](selfboot.md) removes the board's
*need* for those services in the normal path, but the rescue paths still
want them, and something has to hold the serial consoles and bridge the
tailnet. That something should be always on and boring.

It also creates the security boundary. The bench LAN carries services with
no authentication worth the name (TFTP has none; NFS here trusts the
subnet). Those must never face the tailnet, because the tailnet is shared
with external developers. The companion is where that separation is
enforced — twice, independently: in the Tailscale ACL, and in a firewall
that scopes each service to an interface.

```mermaid
flowchart TB
  subgraph TAILNET["Tailnet — WireGuard mesh, GitHub-backed identity"]
    direction LR
    ADMIN["Administrator<br/>group:x5h-admin"]
    DEV["Internal developer<br/>group:x5h-dev (optional middle tier)"]
    EXT["Contractor<br/>group:x5h-ext / tag:x5h-ext"]
  end

  ACL{{"Enforcement 1 — Tailscale ACL grants<br/>identity decides who"}}

  ADMIN -- "dst: * — the whole tailnet" --> ACL
  DEV -- "board :22 + gateway :22" --> ACL
  EXT -- "board :22 only" --> ACL

  subgraph COMPANION["Companion host — always-on bench gateway"]
    direction TB
    TS0["tailscale0<br/>subnet router → 192.168.0.0/24<br/>every Linux node needs --accept-routes"]
    NFT{{"Enforcement 2 — nftables inet x5h<br/>input policy drop; interface decides from where"}}
    SERIAL["Serial consoles<br/>tio + tmux, /dev/ttyUSB*<br/>APU + CR52"]
    BIF["bench NIC 192.168.0.1/24<br/>never-default, ignore-carrier"]
    RESCUE["Rescue services<br/>tftpd :69 · NFSv3 /export/rfs*<br/>rpc.mountd :20048 pinned"]
    UPLINK["uplink NIC<br/>masquerade for the bench"]
    TS0 --> NFT
    NFT -- "ssh :22" --> SERIAL
    NFT -- "forward tailscale0 → bench" --> BIF
    NFT -. "denied — reached tailscale0, not the bench NIC" .-> RESCUE
    BIF --> UPLINK
  end

  ACL == "permitted flows only" ==> TS0

  subgraph BENCH["Bench LAN 192.168.0.0/24 — unauthenticated services live only here"]
    direction TB
    BOARD["R-Car X5H — tsn5 192.168.0.20<br/>AutoSD self-boot from UFS<br/>sshd key-only, everyone lands as root"]
    CR52["CR52 realtime core<br/>firmware slot on UFS, written from Linux<br/>reboot = PSCI cold reset, restarts it too"]
    BOARD --- CR52
  end

  BIF -- "ssh root@192.168.0.20" --> BOARD
  SERIAL -- "USB serial — the only way back when the PHY wedges" --> BOARD
  RESCUE -- "TFTP kernel/dtb + NFS root (rescue boot only)" --> BOARD
  UPLINK -- "container pulls, DNS 1.1.1.1 / 8.8.8.8" --> NET(["Internet"])

  classDef tier fill:#e8f0fe,stroke:#4285f4,color:#111
  classDef gate fill:#fff4e5,stroke:#e8a33d,color:#111
  classDef host fill:#f3f3f3,stroke:#888,color:#111
  classDef board fill:#e6f4ea,stroke:#34a853,color:#111
  class ADMIN,DEV,EXT tier
  class ACL,NFT gate
  class TS0,SERIAL,BIF,RESCUE,UPLINK host
  class BOARD,CR52 board
  linkStyle 6 stroke:#d93025,stroke-width:2px,color:#d93025
```

The serial consoles turn out to matter more than "something has to hold
them" suggests. There is a real failure mode in which the board is booted
and healthy but has no working network, and reports its interface as up
while being unreachable. Serial is then the only way back in. See
[Failure modes](#failure-modes-paid-for-in-hardware).

Assumes Ubuntu 24.04 LTS with two interfaces: `<BIF>` for the bench LAN and
a separate `<uplink>`. Substitute real names throughout. The reference host
used a USB Gigabit adapter for `<BIF>` and Wi-Fi for the uplink; both work,
and both have consequences called out below.

## The two boards

The bench holds two X5H boards behind the companion. They run the **same
image, the same U-Boot environment template and the same partition map**;
the only intended difference between them is the three-line variables file
each is staged from (`boards/x5h1.vars`, `boards/x5h2.vars`).

| | Board 1 `192.168.0.20` | Board 2 `192.168.0.21` |
|---|---|---|
| Default role | `npu` | `npu` |
| Available roles | `cr52`, `npu` | `cr52`, `npu`, `yocto` |
| `HAS_YOCTO` | `0` | `1` |
| Hostname | `autosd-x5h` | `autosd-x5h-2` (`yocto-x5h-2` in the `yocto` role) |
| LUN 1 (AutoSD) | `x5h-boot` 1 GiB / `x5h-root` 12 GiB / `autosd-store` 19 GiB btrfs, PARTUUID `…5e01/02/03` | identical |
| LUN 2 | `yocto-boot` 1 GiB (empty) / `yocto-root` 8 GiB (empty) / `npu-work` rest, PARTUUID `…5e11/12/13` | same map, Yocto partitions populated |
| `x5h-boot` contents | `Image-autosd`, both dtbs, `x5h-env.txt`, `x5h-role.txt` | identical |
| CR52 slot | `actuation_x5h.elf` | identical (its silence remains the open escalation) |
| Bootloader | Stage 2 AI-package chain, DRAM ECC off | identical |
| Access | admin + dev + ext grants | admin only |

`…5eXX` is shorthand for `7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5eXX`. Board 1 gets
the whole LUN 2 map with its two Yocto partitions formatted and left empty,
which is what lets one environment template serve both boards. The roles
themselves are described in [selfboot.md](selfboot.md), "Roles".

Two consequences worth stating plainly:

- **Board 1 now carries the NPU boot path and the NPU payload.** The
  2026-08-25 invariant that it did not is withdrawn, because external
  developers need the NPU there. The vendor NDA material on `npu-work` is
  therefore reachable by every root login on board 1. That is accepted, and
  the Tailscale ACL below is deliberately unchanged.
- **Board 2 is not the Yocto appliance any more.** Its default personality is
  AutoSD in the `npu` role, like board 1; Yocto survives as a third role on
  its second LUN, for vendor-kernel reproduction and vendor reports.

## 1. Base packages and tailnet

```sh
sudo apt update && sudo apt install -y \
  nftables tftpd-hpa nfs-kernel-server tmux tio rsync unattended-upgrades
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale set --advertise-routes=192.168.0.0/24
```

Use `tailscale set`, not `tailscale up`: `set` changes the advertised routes
on a node that is already logged in without re-authenticating it. Approve
the route in the admin console (or let `autoApprovers` do it, section 6),
then confirm with `tailscale status --json` that `Self.PrimaryRoutes`
contains `192.168.0.0/24` — that field, not the advertisement, is what says
the tailnet is actually routing through this node.

Tagging the companion is optional and is discussed in section 6, together
with the device-key expiry that will otherwise take the gateway offline on a
schedule.

> **Every Linux node that needs the bench must run
> `sudo tailscale set --accept-routes`.** Accepting advertised subnet routes
> is *off by default on Linux* (it is on by default on macOS and Windows).
> Without it the node never installs `192.168.0.0/24` and sends bench traffic
> to its own default gateway instead, so `ssh root@192.168.0.20` hangs and
> then fails. Nothing in the tailnet or on the companion looks wrong, which
> makes this read as a firewall or ACL problem for as long as you let it.
> Check with `ip route get 192.168.0.20` and require `dev tailscale0` in the
> answer.

If `apt` exits non-zero while every requested package is installed, look for
unrelated half-configured packages (`dpkg -l | grep -v '^ii'`) before
believing the failure is yours; provisioning scripts should test for the
packages they need rather than trusting apt's exit status.

## 2. Bench LAN and forwarding

The companion takes over `192.168.0.1`, the address the board's kernel
command line already uses as its gateway, so nothing on the board changes
when the cables move. `serverip` in the board's saved U-Boot environment is
the same address, so the netboot rescue paths also need no edit.

```sh
sudo nmcli con add type ethernet ifname <BIF> con-name x5h-lan \
  ipv4.method manual ipv4.addresses 192.168.0.1/24 \
  ipv4.never-default yes ipv6.method disabled \
  connection.autoconnect yes
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-x5h.conf
sudo sysctl --system
```

Three things the obvious version of this gets wrong:

- **Autoconnect priority must beat whatever else claims the NIC, and must be
  computed rather than guessed.** NetworkManager auto-creates a profile for
  any wired NIC, and on a carrier event the winner owns the address. If the
  wrong profile wins, the interface ends up with a link-local address and the
  board's U-Boot fails its `tftp` with `ARP Retry count exceeded` — a symptom
  that points nowhere near NetworkManager. Take the highest
  `autoconnect-priority` among the other profiles on that interface and add
  100, so winning is a property of the configuration and not of activation
  history.
- **`ipv4.never-default yes` and `ipv6.method disabled`** keep a bench
  profile from ever competing for the default route.
- **IPv4 forwarding only.** Enabling `net.ipv6.conf.all.forwarding` buys
  nothing here — the advertised route is IPv4 and the board is IPv4-only —
  while enabling per-interface IPv6 forwarding suppresses kernel RA
  processing and is a plausible way to lose the host's own IPv6 default
  route.

Optionally, keep the address even when the board is powered off:

```sh
printf '[device-x5h]\nmatch-device=interface-name:<BIF>\nignore-carrier=yes\n' \
  | sudo tee /etc/NetworkManager/conf.d/50-x5h-ignore-carrier.conf
sudo systemctl reload NetworkManager
```

Without this, losing carrier makes NetworkManager deactivate the profile and
the companion holds no `192.168.0.1` at all while the board is off. Normal
operation does not care (self-boot never uses TFTP, and the firewall matches
on interface name rather than address), but a *cold* netboot rescue becomes a
race: the board's U-Boot starts its transfer a few seconds after power-on,
and NetworkManager has to have finished assigning the address by then. Either
set `ignore-carrier`, or check `ip -br addr show <BIF>` before starting a
rescue.

## 3. Firewall

Identity is the ACL's job; this file's job is to make sure the
unauthenticated bench services can only ever be reached from the bench
LAN, whatever the ACL says. `/etc/nftables.conf`:

```
#!/usr/sbin/nft -f
# Replace only our own table. A global `flush ruleset` destroys the
# iptables-nft tables that Docker installs, on every nftables restart.
table inet x5h
delete table inet x5h

define BIF = "<BIF>"
define UPLINK = "<uplink>"

table inet x5h {
  chain input {
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif "lo" accept
    # Containers reaching host services. Also see the forward chain: a drop
    # policy in this table vetoes packets that Docker's own table accepted,
    # because every chain at a hook sees the packet and any drop is final.
    iifname "docker0" accept
    # SSH: tailnet and bench LAN.
    iifname { "tailscale0", $BIF } tcp dport 22 accept
    # If the uplink is a shared LAN you administer this box from, admit SSH
    # from that subnet too -- otherwise the tailnet is the single path to a
    # machine that is supposed to run without a keyboard. Scoped to one
    # RFC1918 subnet on one interface; it is not reachable from the internet.
    iifname $UPLINK ip saddr <uplink-subnet> tcp dport 22 accept
    # TFTP + NFS: bench LAN only -- these face no tailnet, ever.
    # 20048 is rpc.mountd, pinned in section 4. The board's rescue netboot
    # mounts with nfsvers=3, so mountd must be reachable or the mount fails;
    # 69/111/2049 alone is not enough.
    iifname $BIF udp dport { 69, 111, 2049, 20048 } accept
    iifname $BIF tcp dport { 111, 2049, 20048 } accept
    iifname $BIF icmp type echo-request accept
    iifname "tailscale0" icmp type echo-request accept
    udp dport 41641 accept
    # mDNS replies arrive as fresh multicast, not as conntrack-established,
    # so a drop policy silently breaks .local resolution in both directions
    # on a host running avahi. Uplink only.
    iifname $UPLINK udp dport 5353 accept
    iifname $UPLINK icmp type echo-request accept
  }
  chain forward {
    type filter hook forward priority 0; policy drop;
    ct state established,related accept
    iifname "tailscale0" oifname $BIF accept
    iifname $BIF oifname $UPLINK accept
    iifname "docker0" accept
    oifname "docker0" accept
  }
  chain postrouting {
    type nat hook postrouting priority 100;
    iifname $BIF oifname $UPLINK masquerade
  }
}
```

```sh
sudo nft -c -f /etc/nftables.conf && sudo systemctl enable --now nftables
```

The masquerade is what lets the board pull container images; the image
ships static resolvers because nothing on the bench LAN serves DNS.

Note what this ruleset deliberately does *not* do: it does not scope SSH by
destination address, so the companion answers on `22` at its bench address
from the tailnet as well. That is intentional — the address a packet is
addressed to says nothing about where it came from, and the interface it
arrived on does.

Before turning this on, inventory what already listens on the host
(`sudo ss -tulpn`). A default-drop input policy on a machine that was
previously unfirewalled will silently cut remote-desktop tools, printer and
device discovery, and anything else with an inbound listener. Outbound stays
unaffected: there is no output chain, and established/related is accepted, so
tools that connect out to a relay keep working while tools that expect direct
inbound connections stop.

## 4. Rescue services and artifact migration

```sh
sudo mkdir -p /srv/tftp /export/rfs /export/rfs-autosd
sudo tee /etc/default/tftpd-hpa >/dev/null <<'EOF'
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/srv/tftp"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure"
EOF
sudo mkdir -p /etc/nfs.conf.d
printf '[mountd]\nport = 20048\n' | sudo tee /etc/nfs.conf.d/50-x5h.conf
printf '/export/rfs 192.168.0.0/24(rw,async,no_root_squash,no_subtree_check)\n/export/rfs-autosd 192.168.0.0/24(rw,async,no_root_squash,no_subtree_check)\n' \
  | sudo tee /etc/exports
sudo systemctl enable --now tftpd-hpa nfs-kernel-server && sudo exportfs -ra
```

Why each of those settings is not optional:

- **`--secure`** is what confines tftpd to `TFTP_DIRECTORY`. Upload
  (`--create`) is deliberately off: netboot only reads, and this host is a
  security boundary.
- **`TFTP_ADDRESS` stays `:69`.** Binding to `192.168.0.1:69` would fail at
  boot whenever the board is powered off and the interface has no address,
  which breaks the reboot drill. The firewall is what scopes tftpd to the
  bench LAN.
- **Everything served over TFTP must be mode 644.** tftpd drops to user
  `tftp`, and an unreadable file makes U-Boot's `tftp` fail with an opaque
  timeout rather than a permission error.
- **`rpc.mountd` on a fixed port.** Its default port is random, so without
  pinning it there is nothing to open in the firewall and the `nfsvers=3`
  rescue mount cannot succeed. Verify with
  `rpcinfo -p localhost | awk '$5=="mountd"'`.

Then move the artifacts across. `/srv/tftp` is world-readable, so only the
receiving side needs root:

```sh
sudo rsync -aH --numeric-ids \
  -e 'ssh -i /home/<admin>/.ssh/id_rsa' \
  <user>@<workstation>:/srv/tftp/ /srv/tftp/
```

The `-e` is required: root's `~/.ssh` has no key of its own.

The two NFS roots are different. They are root-owned trees with hundreds of
files an unprivileged user cannot read, so the *sending* side needs root as
well — and rsync cannot answer a remote sudo password prompt, because its
protocol owns the channel that prompt would use. A cached `sudo` credential
does not help either, since `tty_tickets` binds it to the terminal it was
entered on and rsync's remote command has no terminal. Either grant a
narrowly scoped `NOPASSWD` for rsync on the workstation for the duration of
the copy, or stream through a staging file owned by an unprivileged user, one
tree at a time:

```sh
# on the workstation, where sudo can prompt on a real terminal
sudo tar --numeric-owner --xattrs --xattrs-include='*' --acls -S \
  -cf - -C /export/rfs . \
  | ssh <admin>@<companion> 'cat > /home/<admin>/rfs.tar'

# on the companion
sudo tar --numeric-owner --xattrs --xattrs-include='*' --acls \
  -xf /home/<admin>/rfs.tar -C /export/rfs && rm /home/<admin>/rfs.tar
```

**`--xattrs-include='*'` is load-bearing.** GNU tar excludes the `security.*`
namespace from extraction by default, so without it file capabilities and
SELinux labels are dropped silently — the same class of failure that shipped
a rootfs with no kernel modules earlier in this branch. Verify after the
copy, rather than assuming: the file counts on both sides should match
exactly (`find <tree> | wc -l`, run as the *same* kind of user on both), and
`getcap -r <tree>` should return the same set on both. A tree whose source
has no capabilities at all is a valid answer; the point is that the two
agree.

Then the repo and the serial tooling:

```sh
git clone https://github.com/autowarefoundation/openadkit ~/src/openadkit
sudo usermod -aG dialout "$USER"
```

`dialout` only takes effect in new login sessions, so `/dev/ttyUSB*` stays
unreadable until you log in again — or until the reboot drill below. The
console helper scripts derive their log directory from their own location, so
they work from any checkout path.

Vendor SDK material stays off this list unless the companion is
administrator-only; it must not become reachable from a shared tailnet. None
of the four objectives needs it.

Verify: `showmount -e localhost` lists both exports, and `ss -uln | grep :69`
shows tftpd listening.

## 5. Host hardening and unattended updates

```sh
# put the admin pubkey in ~/.ssh/authorized_keys and verify a key login FIRST
printf 'PasswordAuthentication no\nPermitRootLogin no\n' \
  | sudo tee /etc/ssh/sshd_config.d/50-x5h.conf
sudo mkdir -p /run/sshd && sudo sshd -t
sudo systemctl is-active --quiet ssh.service && sudo systemctl reload ssh.service
sudo sshd -T | grep -x 'passwordauthentication no'
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

Ubuntu 24.04 activates sshd through `ssh.socket`, so `ssh.service` is
inactive and **`systemctl reload ssh` has nothing to reload** — each
connection spawns a fresh sshd that reads the config anyway. Socket
activation also means the privilege separation directory only exists for the
lifetime of a connection, so a bare `sshd -t` fails with
`Missing privilege separation directory: /run/sshd`; create it first. And
because a command failing before the final `&&` of a list is exempt from
`set -e`, the tempting `sshd -t && systemctl reload ssh` will skip the reload
and let a provisioning script report success either way. Assert the live
state with `sshd -T` instead of assuming the file you wrote took effect.

If the companion is a laptop, stop the lid from suspending the bench:

```sh
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchDocked=ignore\nHandleLidSwitchExternalPower=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/50-x5h-nosuspend.conf
```

Applied at next boot. Check the idle-suspend setting of the desktop session
too; a suspended gateway takes the board, TFTP, NFS and the tailnet route
down with it.

## 6. Access tiers

Administrators get the whole bench. External developers get the board's
SSH port and nothing else — not the companion, not TFTP, not NFS.

```mermaid
flowchart LR
  EXT["Contractor<br/>group:x5h-ext, tag:x5h-ext<br/>grant: board only, tcp:22"]
  DEV["Internal developer<br/>group:x5h-dev (optional middle tier)<br/>grant: board + gateway, tcp:22"]
  ADMIN["Administrator<br/>group:x5h-admin<br/>grant: dst * , ip *"]

  subgraph Z0["Zone 0 — no tier reaches this over the tailnet"]
    RESCUE["tftpd :69 · NFSv3 · rpc.mountd :20048<br/>nftables accepts these on the bench NIC only"]
  end

  subgraph Z3["Zone 3 — administrator only"]
    REST["Board ports other than 22<br/>and the companion's other services"]
    TAILNET["Every other machine on the tailnet<br/>this is why the admin grant must stay dst:*"]
    CONSOLE["Tailscale admin console<br/>ACL edits, route approval, onboarding<br/>not gated by ACLs — always the way back"]
  end

  subgraph Z2["Zone 2 — administrator + internal developer"]
    GW["Companion sshd, tcp/22<br/>serial consoles (tio + tmux)<br/>the only way back when the PHY wedges"]
  end

  subgraph Z1["Zone 1 — all three tiers"]
    BOARD["X5H board, tcp/22 only<br/>192.168.0.20 · root by key<br/>reboot, build, run, CR52 slot update"]
  end

  ADMIN ==> BOARD
  ADMIN ==> GW
  ADMIN ==> REST
  ADMIN ==> TAILNET
  ADMIN ==> CONSOLE
  DEV ==> BOARD
  DEV ==> GW
  DEV -. "no grant" .-> REST
  EXT ==> BOARD
  EXT -. "refused — verified from a real tag:x5h-ext node" .-> GW
  EXT -. "refused — board's other ports too" .-> REST
  ADMIN -. "ACL allows it, nftables still drops it<br/>interface decides, not address<br/>reach it by ssh to the companion first" .-> RESCUE

  classDef admin fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px,color:#111
  classDef dev fill:#e6f4ea,stroke:#188038,stroke-width:2px,color:#111
  classDef ext fill:#fef7e0,stroke:#b06000,stroke-width:2px,color:#111
  classDef target fill:#f8f9fa,stroke:#5f6368,color:#111
  classDef blocked fill:#fce8e6,stroke:#d93025,color:#111
  class ADMIN admin
  class DEV dev
  class EXT ext
  class BOARD,GW,REST,TAILNET,CONSOLE target
  class RESCUE blocked

  linkStyle 0,1,2,3,4 stroke:#1a73e8,stroke-width:2px,color:#1a73e8
  linkStyle 5,6 stroke:#188038,stroke-width:2px,color:#188038
  linkStyle 7 stroke:#9aa0a6,stroke-width:1px,color:#9aa0a6
  linkStyle 8 stroke:#b06000,stroke-width:2px,color:#b06000
  linkStyle 9,10 stroke:#d93025,stroke-width:1.5px,color:#d93025
  linkStyle 11 stroke:#d93025,stroke-width:1.5px,color:#d93025
```

Zone 0 is the one worth staring at: **not even the administrator's `dst: *`
reaches TFTP, NFS or mountd over the tailnet**, because the firewall matches
on the interface a packet arrived on rather than on its address. The
administrator gets at those services by opening an SSH session to the
companion first. That is what makes a mistake in the ACL survivable.

The middle tier is optional. Two tiers are enough if everyone who is not
external is an administrator; add `group:x5h-dev` when someone needs the
serial consoles — which is to say, needs to recover a board whose network
has wedged — without getting the rest of the tailnet. The bench services
stay out of reach at either setting, since Zone 0 is enforced by the
firewall and not by identity.

Read the current policy before writing anything. **The policy file replaces
the tailnet's defaults rather than adding to them**, so a merge that only
adds the x5h rules removes the default "allow all your own devices" grant
along the way. Match the syntax already in the file: newer tailnets use
`grants`, older ones `acls`, and mixing them is avoidable work.

```jsonc
{
  "groups": {
    // An identity is however its issuer spells it. Users who sign in through
    // the tailnet's own provider are named as that provider names them: a
    // GitHub-backed tailnet uses GitHub logins, not e-mail addresses, and an
    // address that does not exist here yields an empty group and an admin
    // rule that grants nothing. Invited external users are the exception --
    // they pick their own provider, so their identity is usually an e-mail
    // address and need not have the same shape as the admin's.
    "group:x5h-admin": ["<admin-login>"],
    "group:x5h-ext":   [],   // invited external identities land here
    // Optional middle tier: internal developers who need the board and the
    // gateway's serial consoles, but not the rest of the tailnet. Omit the
    // group and its grant below if two tiers are enough.
    "group:x5h-dev":   [],
  },
  "tagOwners": {
    "tag:x5h-gw":  ["autogroup:admin"],
    "tag:x5h-ext": ["autogroup:admin"],
  },
  "grants": [
    // Administrators keep unrestricted access. Do not narrow this to the
    // gateway and the bench subnet: with the default allow-all grant removed,
    // that is what cuts you off from every other machine on your own tailnet.
    {"src": ["group:x5h-admin"], "dst": ["*"], "ip": ["*"]},
    // Optional internal tier: the board plus the gateway's SSH, so they can
    // drive the serial consoles. Name the gateway by its tag; if it is not
    // tagged, use its node name instead.
    {"src": ["group:x5h-dev"], "dst": ["192.168.0.20", "tag:x5h-gw"], "ip": ["tcp:22"]},
    // External tier. In grants syntax the port restriction lives in "ip",
    // not appended to "dst".
    {"src": ["group:x5h-ext", "tag:x5h-ext"], "dst": ["192.168.0.20"], "ip": ["tcp:22"]},
  ],
  "autoApprovers": {
    "routes": {"192.168.0.0/24": ["tag:x5h-gw", "group:x5h-admin"]},
  },
}
```

Keep the admin console open after saving and confirm you can still reach your
own machines before considering it done. ACLs do not gate console access, so
the console is always the way back.

The board's own sshd is key-only (`PasswordAuthentication no`,
`PermitRootLogin prohibit-password`), so the well-known development root
password is not a network credential. It still works on the serial
console, which is deliberate — that is the recovery path.

### Device key expiry on the gateway

A user-owned node's device key expires (180 days by default). When it does,
the subnet router stops routing and someone has to re-authenticate
interactively — a scheduled outage for an unattended gateway. Check it with
`tailscale status --json` (`Self.KeyExpiry`) and pick one:

- **Disable key expiry** for the device in the admin console. Least
  invasive, and enough on its own.
- **Tag it** `tag:x5h-gw`. Tagged devices have no key expiry and let
  `autoApprovers` re-approve the route by itself, at the cost of
  re-authentication and of no longer matching user-based rules. The admin
  grant above is `dst: ["*"]`, so tagging can be decided independently and
  later.

### Onboarding an external developer

External developers join as **users of this tailnet**, by invitation. Do not
share the gateway node with them instead: **a shared node does not carry its
subnet routes.** The control plane rewrites the ACLs of an externally shared
subnet router so the recipient reaches that node and nothing behind it, and
the board is on the far side of the advertised `192.168.0.0/24` — so a share
leaves the board unreachable, with nothing to correct at either end.

1. Settle it with their employer first. A tailnet by default lets only its
   own Admins accept an invitation to an *external* tailnet, so a developer
   whose company runs Tailscale cannot accept until their IT administrator
   permits it. Discovering this after the invite is issued costs a round
   trip and presents as a fault at this end.
2. Ask them, in the same message, for the delivery address for the invite
   and for the SSH **public** key step 5 installs — the single
   `ssh-ed25519 …` line from their `.pub` file, never the private key. Both
   are yours to request rather than theirs to know: nothing reaches you by
   itself, and an unrequested key eventually arrives in the wrong half.
3. Invite them from the admin console — Users, then *Invite external users*
   — by e-mail or by link. Invites are one-time and expire after 30 days.
   Each user who accepts counts against the tailnet's plan: a hard cap on
   the free tier, and a per-user charge on the paid ones, where there is no
   user limit to plan around.
4. Once they have accepted, read their identity off the Users page and add
   that string to `group:x5h-ext` exactly as shown. They authenticate with
   whichever provider they choose — any supported IdP, or a passkey — so
   what belongs in the group is **not knowable before they accept**, and is
   usually an e-mail address rather than a login of this tailnet's own
   provider.
5. Append their public key to `/etc/ssh/authorized_keys.d/root` on the
   board — or to `config/x5h-authorized-keys` if it should survive an
   image rebuild.
6. Verify with the checks below, from their node.

Steps 4 and 5 are independent, and each is silent when omitted: without the
grant their SSH hangs, without the key it is refused. Doing one and calling
it done is the usual result of splitting them across a day.

Offboarding is the reverse; remember the key on the board outlives the
tailnet removal.

## 7. Verification

### Reboot drill

Set the BIOS to power on after AC loss, then `sudo reboot` and check from
elsewhere on the tailnet:

```sh
ssh <companion> 'tailscale status | head -3 \
  && ip -4 addr show <BIF> | grep -q 192.168.0.1 \
  && showmount -e localhost \
  && ss -uln | grep -q ":69 " \
  && systemctl is-active nftables tftpd-hpa nfs-kernel-server' \
  && echo COMPANION_REBOOT_PASS
```

Use `grep -q`, not `sed -n /:69/p`: `sed` exits 0 whether or not it matched,
so as a link in an `&&` chain it can never fail and the check silently proves
nothing.

### Access tiers

From an admin node:

```sh
tailscale ping <companion> && ssh <companion> true && ssh root@192.168.0.20 true \
  && echo ACL_ADMIN_OK
```

If the admin key has a passphrase, run this with the key loaded into an
agent. Without one, ssh cannot produce a signature and reports
`Permission denied (publickey)` — while the server-side log and `ssh -vv`
both show `Server accepts key`. The failure is local; the key is fine.

From a node joined with a `tag:x5h-ext` auth key, using a key authorised on
the board. Confirm the node is really tag-owned before believing any of it:

```sh
tailscale status --json | grep -A2 '"Tags"'   # must list tag:x5h-ext
```

A node that joined user-owned matches `group:x5h-admin`, is granted
`dst: ["*"]`, and will therefore reach *everything* — which reads as a broken
ACL rather than a broken test. Tags come from the auth key, so the key has to
be created with the tag selected; alternatively a tag owner can self-assign
it with `tailscale up --advertise-tags=tag:x5h-ext --force-reauth`. Use one
mechanism or the other, not both.

Then probe, from that node:

| destination | expected | what it isolates |
|---|---|---|
| `192.168.0.20:22` | reachable | the tier still does its job; positive control |
| `192.168.0.20:2049` | blocked | the ACL restricts the *port*, not just the host |
| `<companion tailnet IP>:22` | blocked | the ACL alone — nftables admits tcp/22 on `tailscale0` |
| `192.168.0.1:2049` | blocked | both layers at once |

Both layers **drop** rather than reject, so a blocked probe does not fail
fast — it hangs until whatever timeout you imposed. With
`timeout 6 tailscale nc <host> <port> </dev/null`, exit 0 means the
connection was established and closed on our EOF, and exit 124 means the
handshake never completed. Getting that mapping backwards turns a working
boundary into a reported failure, so assert that the permitted destination
and a blocked one land on *different* exit statuses before reporting a
verdict at all. Note also that a bare "no bytes received" is not evidence of
blocking: NFS sends no banner on connect. For the positive control, hold
stdin open and read the SSH banner as payload proof.

UDP 69 is not worth probing directly: a UDP connect test cannot distinguish
"filtered" from "no reply". It sits in the same nftables rule and the same
interface scope as udp/2049, so the NFS result covers it by construction.

### Two-board parity

The two boards are meant to differ only in their variables file, and that is
checked rather than assumed. Collect a manifest from each board and diff
them on the companion:

```sh
cd platforms/autosd/x5h
for b in 20 21; do
  ssh root@192.168.0.$b /usr/sbin/x5h-manifest.sh > /tmp/m-$b.txt
done
scripts/x5h-parity.sh /tmp/m-20.txt boards/x5h1.vars \
                      /tmp/m-21.txt boards/x5h2.vars
```

Expect `BOARD_PARITY_PASS`. Anything else prints the residual diff first and
then `BOARD_PARITY_FAIL reason=<residual_diff|bad_args|same_manifest|bad_vars|
incomplete_manifest>`.

Three things about this that matter more than they look:

- **Redirect stdout only.** `x5h-manifest.sh` puts the manifest on stdout and
  its own marker on stderr, precisely so a marker cannot be captured into the
  manifest file and read back as a key. Watch the terminal for
  `X5H_MANIFEST_OK`; a `X5H_MANIFEST_FAIL reason=<slug>` means the manifest is
  empty and the collection has to be repeated, not that the board diverged.
  If a failure marker does end up inside a file (a stray `2>&1`), parity
  refuses it with `missing=manifest_marked_failed` rather than diffing it.
- **Parity enforces a completeness floor.** A manifest missing `kernel`,
  `cmdline`, `env.md5`, any `boot.*` or any `unit.*` key is rejected as
  `incomplete_manifest`. Two boards that both lost the same category compare
  equal, which is the false pass this floor exists to stop.
- **`env.md5` is the U-Boot environment, normalized.** The raw
  `boot.x5h-env.txt` hash is exempt because the rendered environment
  legitimately differs per board; `env.md5` blanks only the client-address and
  hostname fields of every `ip=` word and hashes the rest, so
  `clk_ignore_unused`, the `root=PARTUUID=` values and the per-role load
  addresses are all compared. It is not exempt from the diff.

`fs.yocto-*` is exempt only when the two boards disagree about `HAS_YOCTO`.
Point both invocations at variables files with the same value and those
filesystems are compared like anything else.

**Root-access grants are intentionally per board and are exempt from the
verdict.** Board 1 carries admin + dev + ext, board 2 admin only (see "The two
boards" above), and `stage-board.sh backup-keys` / `prepare-root` carry each
board's own live `/etc/ssh/authorized_keys.d/root` forward across a re-image,
so the two files are guaranteed to differ and an equality check on them would
make `BOARD_PARITY_PASS` unreachable. `x5h-parity.sh` therefore allow-lists
`file./etc/ssh/authorized_keys.d/*` alongside the ssh host keys. The grants are
still emitted into the manifest, so they are reviewed by **reading the two
manifests** rather than by the parity verdict:

```sh
diff <(grep 'authorized_keys' /tmp/m-20.txt) <(grep 'authorized_keys' /tmp/m-21.txt)
ssh root@192.168.0.21 'cut -d" " -f3 /etc/ssh/authorized_keys.d/root'   # who is granted
```

Never close a residual here by copying one board's keys onto the other: that
would grant board 2 to external developers, which the access model above
deliberately forbids. `sshd*` is in the manifest's unit-file scan, so whether
the daemon is *enabled* is still compared normally on both boards.

### Netboot rescue through the companion

One-shot boots from the U-Boot prompt; neither writes the environment, so
the board returns to UFS self-boot on the next reset with nothing to undo.
`printenv` first, as always.

```
=> printenv bootcmd role rescue_autosd rescue_yocto_nfs
=> ping 192.168.0.1            # host is alive -> the bench path works
=> run rescue_yocto_nfs        # TFTP kernel+dtb, NFS root /export/rfs
=> run rescue_autosd           # TFTP kernel+dtb, NFS root /export/rfs-autosd
```

`bootcmd_yocto` is **not** the NFS rescue any more: it is the self-boot Yocto
role from the second LUN. The NFS rescue is `rescue_yocto_nfs`, which runs
the `bootcmd_yocto_nfs` the environment import renamed the old value into.
On a board where that rename was skipped, `rescue_yocto_nfs` will fail on an
undefined variable, and the fix is to reconstruct `bootcmd_yocto_nfs` from
the `printenv` backup rather than to redefine `bootcmd_yocto`.

Confirm on the booted system that the root really is the companion's export,
rather than trusting that the command ran:

```sh
findmnt -n -o SOURCE,FSTYPE /                    # 192.168.0.1:/export/... nfs
findmnt -n -o OPTIONS / | tr ',' '\n' | grep -E 'vers|mount'
```

The second command is the one that proves the mountd rule earns its place:
`mountvers=3` and `mountproto=tcp` mean the client talked to `rpc.mountd`
over TCP, which the original 69/111/2049 ruleset would have dropped.

Two expected results that are not faults: the netbooted AutoSD root is the
pre-self-boot image and has **no sshd**, so verify it over serial; and
podman logs overlayfs complaints there because its store cannot sit on NFS,
which is exactly why self-boot uses a btrfs partition instead.

### Remote workday rehearsal

From off-bench, over the tailnet only: smoke, remote reset, wait, smoke.

```sh
ssh root@192.168.0.20 sh /usr/sbin/selfboot-smoke.sh   # boot A
ssh root@192.168.0.20 reboot
# wait for it to answer again, then
ssh root@192.168.0.20 sh /usr/sbin/selfboot-smoke.sh   # boot B
```

`selfboot-smoke.sh` is repeatable now and reports the role it found on its
PASS line. It no longer ends in a CR52 round trip: that step restarted
remoteproc, raced `rpmsg-eth.service` and oopsed `rpmsg_char`, which under the
`oops=panic` bootargs every role carries would now reboot the board mid
rehearsal. The once-per-boot constraint went with it. **The CR52 link check
that replaced it, `rpmsg-eth-smoke.sh`, still passes once per boot**, because
the CR52 announces its RPMsg endpoint exactly once per SoC reset; a second run
in the same boot fails no matter how long it waits, which reads as a
regression in whatever you last changed. Budget one link check per boot and
put a reset between the tiers you verify. `dmesg | grep -c 'creating channel'`
returning 0 says the current boot's session is still unused.

The rehearsal is also the cheapest place to exercise a role switch, since it
already ends in a reset:

```sh
ssh root@192.168.0.20 x5h-role                  # current= and next=
ssh root@192.168.0.20 x5h-role set cr52 --reboot
# wait, then
ssh root@192.168.0.20 'cat /run/x5h/role; sh /usr/sbin/selfboot-smoke.sh'
ssh root@192.168.0.20 x5h-role set npu --reboot  # leave it in the default role
```

The role is sticky, so a board left in `cr52` stays there through every
reboot, panic and watchdog reset until someone sets it back.

Comparing `/proc/sys/kernel/random/boot_id` either side of the reset is a
cheap way to prove the board actually reset rather than merely stayed up.

## Failure modes paid for in hardware

**The bench link can come up unusable after returning from a netboot
rescue.** Symptom: the board boots fine from UFS and the console is healthy,
but the Ethernet switch driver logs a register-wait timeout, the PHY fails
master/slave resolution, and the PHY state machine halts with a WARNING
backtrace. The trap is that **the board then reports its interface as `UP`
with `LOWER_UP` and its address assigned** while being completely
unreachable, because the driver reports carrier optimistically. Nothing on
the board looks wrong from the board.

Another `reboot` clears it. Since the network is what is broken, that reboot
has to be issued over serial — which is the concrete reason the companion
holds the consoles rather than merely being near the board.

**Do not treat a timeout as a dead board.** A good reset answers again in
about 30 seconds; a link that fails to negotiate can leave the board silent
for minutes and then recover on its own. Polling for 155 seconds and
concluding failure has already produced one wrong diagnosis. Look at the
serial console before deciding.

**The board's `tsn5` MAC address is randomised on every boot.** Anything
built on a stable MAC — DHCP reservations, MAC filtering, static ARP entries
— will not work.

**The board has no RTC or NTP on the bench LAN**, so its log timestamps are
wrong by days. Correlate against the companion's clock, not the board's.

## Related

- [UFS self-boot](selfboot.md) — why the board no longer depends on this
  host, the rescue commands that still do, the three boot roles, and the
  `stage-board.sh` sequence that runs on this host.
- [NPU bring-up](npu-bringup.md) covers the `npu` role's container contract,
  which is what board 1's external developers consume.
- [CR52 slot update](cr52-slot-update.md) — the remote firmware workflow
  this host makes reachable.
