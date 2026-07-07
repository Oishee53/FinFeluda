import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteInvestigation,
  getInvestigationDetail,
  getInvestigationReviews,
  getInvestigationSources,
  listInvestigations,
} from "../api/investigations";

export function useInvestigations() {
  return useQuery({
    queryKey: ["investigations"],
    queryFn: listInvestigations,
  });
}

export function useInvestigation(id) {
  return useQuery({
    queryKey: ["investigation", id],
    queryFn: () => getInvestigationDetail(id),
    enabled: Boolean(id),
  });
}

export function useInvestigationSources(id) {
  return useQuery({
    queryKey: ["investigation-sources", id],
    queryFn: () => getInvestigationSources(id),
    enabled: Boolean(id),
  });
}

export function useInvestigationReviews(id) {
  return useQuery({
    queryKey: ["investigation-reviews", id],
    queryFn: () => getInvestigationReviews(id),
    enabled: Boolean(id),
  });
}

export function useDeleteInvestigation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteInvestigation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
    },
  });
}
