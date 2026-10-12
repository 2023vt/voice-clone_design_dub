import { useEngines } from './use-engines';
import { useComputeTarget } from './use-compute-target';

/** Local metadata cannot describe a worker's independently installed model. */
export function useTtsLanguages(operation = 'clone') {
  const engines = useEngines();
  const target = useComputeTarget(true, operation);
  const remote = target.data?.active.remote;
  const checkingTarget = target.isLoading;
  const unknownTarget = target.isError;
  const names =
    remote || checkingTarget || unknownTarget || engines.isError
      ? null
      : engines.activeTts?.supported_language_names;
  return {
    names,
    modelLabel: remote
      ? target.data?.active.label
      : engines.data?.tts?.active_model?.split('/').pop() ||
        engines.activeTts?.display_name?.split(' (')[0],
    state:
      engines.isLoading || checkingTarget
        ? ('loading' as const)
        : engines.isError || unknownTarget
          ? ('error' as const)
          : names == null
            ? ('unknown' as const)
            : ('known' as const),
  };
}
