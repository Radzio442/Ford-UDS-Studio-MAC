# Ford SecurityAccess database (legacy 3-byte)

Ford UDS Studio 2.11.2 separates the universal legacy key algorithm from the
ECU-specific secret database.

## Selection order

1. A project-specific VBF part-number profile already present in Ford UDS Studio.
2. A live DID `F111` hardware-prefix rule imported from the supplied VBFlasher database.
3. An older ECU-wide fallback entry when no more specific rule exists.

The application logs which rule was selected before sending the key.

## Algorithm

Legacy Ford SecurityAccess uses a 3-byte seed and a 5-byte/40-bit secret.  The
same LFSR key generator is reused across the supported legacy ECU families;
the secret changes by family/hardware and sometimes by SecurityAccess level.

## Imported profile data

The VBFlasher database contributes rules for IPC, BCM, ACM, PSCM, IPMA, RCM,
ABS, FCDIM/FDIM, PCM, TCM and DEATC/HVAC, including hardware-prefix based SBL
recommendations and the IPMA halfword SBL-call behavior.

SBL binaries themselves are not embedded by this integration; the database
only records recommended filenames.

## Safety

If no matching secret is known, Ford UDS Studio stops instead of guessing a key.
Always verify the live F111 identity and loaded VBF/SBL before programming.


## 2.11.3 selection order

SecurityAccess selection is now verified-first:

1. VBF/profile-specific rule
2. specific non-empty F111 prefix rule
3. verified ECU-wide legacy fallback
4. generic wildcard rule only as a last resort

Verified level `0x01` values restored for tested modules:

- IPC `0x720`: `0x4A7722`
- ACM `0x727`: `0x123BF9`
- APIM `0x7D0`: `0x123BF9`

The previous 2.11.2 behavior allowed empty-prefix (`*`) rules to override
these verified values. That caused valid 3-byte seeds to be calculated with
the wrong 5-byte secret.
