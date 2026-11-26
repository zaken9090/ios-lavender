"""lavender: SMEM lookups also read the partition's cached entries (patch 1048).

After the modem came up (run e46) GLINK stayed silent: the modem had made the descriptor (item 478)
but its FIFO (item 480) was never found, so nothing was read. smem_get() walked only the entries
that grow up from the partition's start ("uncached"); a private partition has a second list that
grows down from its end ("cached", Linux qcom_smem_get_private() reads both). That list is read
now, with the cache line size of the partition's table entry. Diagnostics: the items of both lists
are logged once at GLINK start and in every summary, where the SError record is printed too.

usage: python mk_smemcached.py XNU_TREE   (after mk_serror.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		if (h->canary != 0xA5A5) {
			return NULL;
		}
		if (h->item == item) {
			if (size != NULL) {
				*size = h->size - h->pad_data;
			}
			return e + sizeof(*h) + h->pad_hdr;
		}
		e += sizeof(*h) + h->pad_hdr + h->size;
	}
	return NULL;
}
''', '''		if (h->canary != 0xA5A5) {
			break;
		}
		if (h->item == item) {
			if (size != NULL) {
				*size = h->size - h->pad_data;
			}
			return e + sizeof(*h) + h->pad_hdr;
		}
		e += sizeof(*h) + h->pad_hdr + h->size;
	}
	/* lavender: the cached entries, from the partition's end downwards; the data lies below its header */
	uint32_t step = smem_cached_step(p);
	if (step == 0 || p->free_cached > p->size || p->free_cached < p->free_uncached) {
		return NULL;
	}
	e = (uint8_t *)p + p->size - step;
	end = (uint8_t *)p + p->free_cached;
	while (e > end) {
		struct smem_priv_entry *h = (struct smem_priv_entry *)e;
		if (h->canary != 0xA5A5 || h->size > (uint32_t)(e - end)) {
			break;
		}
		if (h->item == item) {
			if (size != NULL) {
				*size = h->size - h->pad_data;
			}
			return e - h->size;
		}
		if ((uint32_t)(e - end) < h->size + step) {
			break;
		}
		e -= h->size + step;
	}
	return NULL;
}

/* the items of a partition, both lists, as one log line each */
static void
smem_list(struct smem_part_hdr *p)
{
	char line[220];
	int n;
	if (p == NULL || memcmp(p->magic, "$PRT", 4) != 0 || p->free_uncached > p->size) {
		return;
	}
	uint32_t step = smem_cached_step(p);
	n = snprintf(line, sizeof(line), "SMEM size %#x uncached to %#x, cached from %#x (header step %u):", p->size, p->free_uncached,
	    p->free_cached, step);
	uint8_t *e = (uint8_t *)p + sizeof(*p), *end = (uint8_t *)p + p->free_uncached;
	while (e + sizeof(struct smem_priv_entry) <= end && n < (int)sizeof(line) - 16) {
		struct smem_priv_entry *h = (struct smem_priv_entry *)e;
		if (h->canary != 0xA5A5) {
			break;
		}
		n += snprintf(line + n, sizeof(line) - n, " %u", h->item);
		e += sizeof(*h) + h->pad_hdr + h->size;
	}
	LOG("%s", line);
	if (step == 0 || p->free_cached > p->size || p->free_cached < p->free_uncached) {
		return;
	}
	n = snprintf(line, sizeof(line), "SMEM cached:");
	e = (uint8_t *)p + p->size - step;
	end = (uint8_t *)p + p->free_cached;
	while (e > end && n < (int)sizeof(line) - 24) {
		struct smem_priv_entry *h = (struct smem_priv_entry *)e;
		if (h->canary != 0xA5A5) {
			n += snprintf(line + n, sizeof(line) - n, " (canary %#x)", h->canary);
			break;
		}
		n += snprintf(line + n, sizeof(line) - n, " %u(%u)", h->item, h->size);
		if ((uint32_t)(e - end) < h->size + step) {
			break;
		}
		e -= h->size + step;
	}
	LOG("%s", line);
}
''')
sub('''static void *
smem_get(struct smem_part_hdr *p, uint16_t item, uint32_t *size)
{
''', '''/* how far apart the headers of cached entries are: the entry header rounded up to the partition's cache line */
static uint32_t
smem_cached_step(struct smem_part_hdr *p)
{
	struct smem_pt *pt = (struct smem_pt *)(smem + SMEM_SIZE - 0x1000);
	struct smem_pt_entry *e = (struct smem_pt_entry *)(pt + 1);

	if (memcmp(pt->magic, "$TOC", 4) != 0 || pt->num_entries > 64) {
		return 0;
	}
	for (uint32_t i = 0; i < pt->num_entries; i++) {
		if (smem + e[i].offset == (uint8_t *)p) {
			uint32_t cl = e[i].cacheline;
			if (cl == 0 || (cl & (cl - 1)) != 0 || cl > 4096) {
				return 0;
			}
			return ((uint32_t)sizeof(struct smem_priv_entry) + cl - 1) & ~(cl - 1);
		}
	}
	return 0;
}

static void *
smem_get(struct smem_part_hdr *p, uint16_t item, uint32_t *size)
{
''')
sub('''static bool
glink_start(struct smem_part_hdr *part)
{
''', '''static struct smem_part_hdr *g_part;
static void smem_list(struct smem_part_hdr *p);
static void lv_serror_report(const char *when);

static bool
glink_start(struct smem_part_hdr *part)
{
	g_part = part;
	smem_list(part);
''')
sub('''	    q_modem_node, q_hello_rx, q_srv_count, q_resumes);
	svc_summary();
''', '''	    q_modem_node, q_hello_rx, q_srv_count, q_resumes);
	smem_list(g_part);
	lv_serror_report("summary");
	svc_summary();
''')
open(path, 'w', newline='\n').write(s)
print('ok')
