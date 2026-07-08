import { useMutation } from '@tanstack/react-query';
import { apiHandler } from '../api';
import type { EmailNotesParams } from '@dna/core';

export function useEmailNotes() {
  return useMutation({
    mutationFn: (params: EmailNotesParams) => apiHandler.emailNotes(params),
  });
}
