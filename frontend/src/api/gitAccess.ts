import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** La clé privée n'y figure que par le slug du secret qui la porte. */
export interface ClientCertificate {
  id: string;
  label: string;
  cert_pem: string;
  /** Lue dans le certificat par le serveur ; null s'il ne se lit pas. */
  public_key_pem: string | null;
  key_secret_slug: string;
  not_after: string;
  /** Connexions qui s'en servent : un certificat utilisé ne se supprime pas. */
  connections: string[];
  created_at: string;
  updated_at: string;
}

export interface CertificateInput {
  label: string;
  cert_pem: string;
  key_secret_slug: string;
}

/** Miles génère la clé (rangée en secret) et un certificat auto-signé. */
export interface CertificateGeneration {
  id: string;
  label: string;
  validity_days: number;
}

/** Une forge ou une organisation, et son accès : PAT, certificat, ou les deux. */
export interface GitConnection {
  id: string;
  label: string;
  base_url: string;
  token_secret_slug: string | null;
  certificate_id: string | null;
  workspaces: string[];
  created_at: string;
  updated_at: string;
}

export interface ConnectionInput {
  label: string;
  base_url: string;
  token_secret_slug: string | null;
  certificate_id: string | null;
}

const CERTIFICATES = ["client-certificates"] as const;
const CONNECTIONS = ["git-connections"] as const;
// Un changement d'accès réécrit le dernier essai des workspaces concernés.
const WORKSPACES = ["workspaces"] as const;

function path(root: string, id?: string) {
  return id === undefined ? root : `${root}/${encodeURIComponent(id)}`;
}

function useInvalidating<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all(
        [CERTIFICATES, CONNECTIONS, WORKSPACES].map((queryKey) =>
          client.invalidateQueries({ queryKey }),
        ),
      );
    },
  });
}

export function useCertificates() {
  return useQuery({
    queryKey: CERTIFICATES,
    queryFn: ({ signal }) => request<ClientCertificate[]>("/api/client-certificates", { signal }),
  });
}

export function useCreateCertificate() {
  return useInvalidating((input: CertificateInput & { id: string }) =>
    request<ClientCertificate>("/api/client-certificates", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useGenerateCertificate() {
  return useInvalidating((input: CertificateGeneration) =>
    request<ClientCertificate>("/api/client-certificates/generate", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useReplaceCertificate(id: string) {
  return useInvalidating((input: CertificateInput & { verification_suffix: string }) =>
    request<ClientCertificate>(path("/api/client-certificates", id), {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  );
}

export function useDeleteCertificate() {
  return useInvalidating((id: string) =>
    request<undefined>(path("/api/client-certificates", id), { method: "DELETE" }),
  );
}

export function useConnections() {
  return useQuery({
    queryKey: CONNECTIONS,
    queryFn: ({ signal }) => request<GitConnection[]>("/api/git-connections", { signal }),
  });
}

export function useCreateConnection() {
  return useInvalidating((input: ConnectionInput & { id: string }) =>
    request<GitConnection>("/api/git-connections", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useUpdateConnection(id: string) {
  return useInvalidating((input: ConnectionInput & { verification_suffix: string }) =>
    request<GitConnection>(path("/api/git-connections", id), {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  );
}

export function useDeleteConnection() {
  return useInvalidating((id: string) =>
    request<undefined>(path("/api/git-connections", id), { method: "DELETE" }),
  );
}
