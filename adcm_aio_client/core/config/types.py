type ParameterName = str
type ParameterDisplayName = str
type AnyParameterName = str

type LevelNames = tuple[ParameterName, ...]


type SimpleParameterValue = float | int | bool | str
type ComplexParameterValue = dict | list
type ParameterValueOrNone = SimpleParameterValue | ComplexParameterValue | None
