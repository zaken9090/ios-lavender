"""lavender: audio A2/A3 - boot the SDM660 ADSP with TopazAudio's loader (patch 1119).

Run e132 (xnu 1118, A1): on I2C6 only 0x3A answers, and only with GPIO 77 high - the speaker
amplifier is a MAX98927 (reset active low, no firmware). NFC (0x28) is not powered.

TopazAudio.cpp (written for SM6225) already has what A2/A3 need: PAS id 1 load of image/adsp.mdt
+ .bNN from the modem partition through TopazModem's FAT reader, SMP2P items 429/443 (bit 10),
"slave-kernel" READY wait, crash reason (SMEM 423), GLINK on the ADSP's SMEM FIFOs and a QRTR
endpoint with pd-mapper. Lavender values (stock DT, docs/AUDIO-PLAN.md): carveout
adsp_fw_region 0x92A00000 + 0x1E00000 (outside the RAM XNU gets, which starts at 4 GB), GLINK
doorbell APCS bit 9 (SMP2P bit 10 and the items are the same).

Its SM6225 parts stay unused: GPR/AudioReach polls only a channel this firmware (APR, ADSP.VT.4.0)
does not open, so its SPF state never becomes READY and codec_bringup() (SM6225 LPASS, WCD937x,
SoundWire) is never reached. Start: no longer from AppleCLCD::start at boot, but from the
lavender audio thread after A1, when the modem is up (SMEM, APCS, SCM, pool ready) - boot-arg
adsp=1 as before, with audio=1.

Expected in the log ("TopazAudio:" lines): PAS init_image/mem_setup/auth_and_reset ret 0, item
443, slave-kernel READY, GLINK version/channels the ADSP opens (names show the APR channel).

usage: python mk_audio3.py XNU_TREE   (after mk_mgswap.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
patch(ta, '''#define ADSP_CARVE_PA       0x53800000u         /* DT pil_adsp_region */
#define ADSP_CARVE_SIZE     0x02300000u''', '''#define ADSP_CARVE_PA       0x92A00000u         /* lavender DT adsp_fw_region (mk_audio3.py) */
#define ADSP_CARVE_SIZE     0x01E00000u''')
patch(ta, '''#define ADSP_GLINK_BIT      8''', '''#define ADSP_GLINK_BIT      9                   /* lavender: APCS bit 9 (glink lpass irq-mask 0x200) */''')

fb = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
patch(fb, '''	topaz_audio_init();
''', '''	/* lavender: the ADSP is started by the audio thread once the modem is up (mk_audio3.py) */
''')

la = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
patch(la, '''extern "C" void lv_audio_start(void);
''', '''extern "C" void lv_audio_start(void);
extern "C" void topaz_audio_init(void);         /* TopazAudio.cpp: ADSP boot, GLINK, QRTR (adsp=1) */
''')
patch(la, '''	LOG("A1 done");
''', '''	LOG("A1 done");
	topaz_audio_init();                             /* A2/A3 with boot-arg adsp=1 */
''')
print('ok')
