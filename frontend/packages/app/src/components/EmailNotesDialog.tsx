import { useEffect, useState } from 'react';
import {
  Button,
  Callout,
  Dialog,
  Flex,
  Text,
  TextField,
} from '@radix-ui/themes';
import { Info, TriangleAlert } from 'lucide-react';
import { useEmailNotes } from '../hooks/useEmailNotes';
import { useRecordingReadiness } from '../hooks/useRecordingReadiness';
import { RecordingReadinessPanel } from './RecordingReadiness';

interface EmailNotesDialogProps {
  open: boolean;
  onClose: () => void;
  playlistId: number;
  userEmail: string;
  /**
   * Notes still waiting to be published. The email is built from the drafts, not
   * from ShotGrid, so anything unpublished goes out in it while ShotGrid still
   * has the old text — worth saying, not worth blocking.
   */
  unpublishedCount?: number;
}

export function EmailNotesDialog({
  open,
  onClose,
  playlistId,
  userEmail,
  unpublishedCount = 0,
}: EmailNotesDialogProps) {
  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [subject, setSubject] = useState('');
  const [sent, setSent] = useState(false);
  // Deliberate, per-opening consent to send ahead of the checks. It resets with the dialog: an
  // override belongs to the send it was given for, not to the playlist.
  const [overrideReadiness, setOverrideReadiness] = useState(false);

  const { mutateAsync, isPending, isError, error, reset } = useEmailNotes();
  const readiness = useRecordingReadiness(playlistId);
  const held = readiness.blocking && !overrideReadiness;

  useEffect(() => {
    if (open) {
      reset();
      setSent(false);
      setOverrideReadiness(false);
    }
  }, [open, reset]);

  const handleSend = async () => {
    await mutateAsync({
      playlistId,
      request: {
        to,
        cc: cc || undefined,
        subject: subject || undefined,
        sent_by: userEmail,
      },
    });
    setSent(true);
  };

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => !o && !isPending && onClose()}
    >
      <Dialog.Content maxWidth="480px">
        <Dialog.Title>Email Notes</Dialog.Title>
        <Dialog.Description style={{ display: 'none' }}>
          Send playlist notes and transcripts by email.
        </Dialog.Description>

        {sent ? (
          <Flex direction="column" gap="4">
            <Callout.Root color="green">
              <Callout.Icon>
                <Info size={16} />
              </Callout.Icon>
              <Callout.Text>Email sent successfully.</Callout.Text>
            </Callout.Root>
            <Flex justify="end">
              <Dialog.Close>
                <Button onClick={onClose}>Close</Button>
              </Dialog.Close>
            </Flex>
          </Flex>
        ) : (
          <Flex direction="column" gap="3">
            {unpublishedCount > 0 && (
              <Callout.Root color="amber">
                <Callout.Icon>
                  <TriangleAlert size={16} />
                </Callout.Icon>
                <Callout.Text>
                  {unpublishedCount === 1
                    ? '1 note has not been published to ShotGrid yet.'
                    : `${unpublishedCount} notes have not been published to ShotGrid yet.`}{' '}
                  They will still be in this email, so it and ShotGrid will not
                  match. Publishing first is usually what you want.
                </Callout.Text>
              </Callout.Root>
            )}
            <RecordingReadinessPanel readiness={readiness} />
            <label>
              <Text size="2" weight="medium" mb="1" as="div">
                To
              </Text>
              <TextField.Root
                placeholder="recipient@example.com"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
            <label>
              <Text size="2" weight="medium" mb="1" as="div">
                CC <Text color="gray">(optional)</Text>
              </Text>
              <TextField.Root
                placeholder="cc@example.com"
                value={cc}
                onChange={(e) => setCc(e.target.value)}
              />
            </label>
            <label>
              <Text size="2" weight="medium" mb="1" as="div">
                Subject <Text color="gray">(optional)</Text>
              </Text>
              <TextField.Root
                placeholder="Auto-generated from playlist name"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              />
            </label>

            {isError && (
              <Callout.Root color="red">
                <Callout.Icon>
                  <Info size={16} />
                </Callout.Icon>
                <Callout.Text>
                  {(error as Error)?.message || 'Failed to send email'}
                </Callout.Text>
              </Callout.Root>
            )}

            <Flex direction="column" gap="2" mt="2">
              <Flex justify="end" gap="2">
                <Dialog.Close>
                  <Button variant="soft" color="gray" disabled={isPending}>
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button
                  disabled={isPending || !to.trim() || held}
                  onClick={() => void handleSend()}
                >
                  {isPending ? 'Sending…' : 'Send'}
                </Button>
              </Flex>
              {/*
                The escape hatch, and the reason the gate can be strict without being a trap.
                Waiting is the right default — the meeting is still landing — but the decision to
                send anyway belongs to the person, who can see above exactly what is outstanding.
              */}
              {held && (
                <Flex justify="end">
                  <Button
                    variant="ghost"
                    color="gray"
                    size="1"
                    disabled={isPending || !to.trim()}
                    onClick={() => setOverrideReadiness(true)}
                  >
                    Send anyway ({readiness.passed} of {readiness.total} ready)
                  </Button>
                </Flex>
              )}
            </Flex>
          </Flex>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
